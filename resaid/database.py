#!/usr/bin/env python3
"""
Database interface for RESAID to read industry standard databases
"""

import logging
import os
import sqlite3
import subprocess
import traceback
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

from ._strict import StrictAttributes
from .dca import decline_curve

logger = logging.getLogger(__name__)


class DatabaseInterface(StrictAttributes):
    """
    Flexible interface for reading industry standard databases and generating DCA forecasts
    
    Supports:
    - ARIES databases (.mdb, .accdb files) - Access format, via pyodbc and the
      Microsoft Access ODBC driver
    - PhdWin databases (.phd, .mod, .tps, .phz files) - TopSpeed format, converted to
      a temporary SQLite database via pytopspeed-modernized (experimental)

    Install the drivers with ``pip install "resaid[database]"``. Used as a context
    manager, the connection (and any temporary SQLite file) is closed on exit; the
    connection itself is opened by ``connect()`` or the first data call.
    """
    
    def __init__(self, db_path: str | Path):
        """
        Initialize database interface
        
        Args:
            db_path: Path to database file
        """
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database file not found: {self.db_path}")
        
        self.db_type = self._detect_db_type()
        self.connection: Any | None = None
        # Why the last connect() attempt failed, one entry per method tried.
        self._connect_errors: list[str] = []
        self._temp_db_path: str | None = None
        self._production_data: pd.DataFrame | None = None
        self._header_data: pd.DataFrame | None = None
        
        # Column mapping configuration - maps RESAID fields to database columns
        self.column_mapping: dict[str, str] = {}
        
        # Table configuration - maps table types to actual table names
        self.table_mapping: dict[str, str] = {}

        # Header column mapping; ``_header_mapping_is_default`` marks a built-in default
        # (missing optional columns are then skipped instead of raising).
        self.header_column_mapping: dict[str, str] = {}
        self._header_mapping_is_default = False
        
    def _detect_db_type(self) -> str:
        """Detect database type from the file extension"""
        ext = self.db_path.suffix.lower()
        
        if ext in ['.mdb', '.accdb']:
            return 'access'  # Generic Access database
        elif ext in ['.phd', '.mod', '.tps', '.phz']:
            return 'phdwin'  # PhdWin TopSpeed database
        else:
            raise ValueError(f"Unsupported database format: {ext}")
    
    def _try_pyodbc_connection(self) -> bool:
        """Try to establish pyodbc connection if available"""
        try:
            import pyodbc  # pyright: ignore[reportMissingImports]  # optional: resaid[database]
            conn_str = f"Driver={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={self.db_path.absolute()}"
            self.connection = pyodbc.connect(conn_str)
            return True
        except ImportError:
            self._connect_errors.append('pyodbc is not installed (pip install "resaid[database]")')
            return False
        except Exception as e:  # noqa: BLE001 - any driver error means not connected
            self._connect_errors.append(
                f"pyodbc could not open the file with the Microsoft Access ODBC driver: {e}"
            )
            return False
    
    def _try_jpype_connection(self) -> bool:
        """
        Placeholder for a JPype/UCanAccess connection; not implemented.

        Always returns False. Note that it starts a JVM (without UCanAccess on the
        classpath) as a side effect when jpype is installed.
        """
        try:
            import jpype  # pyright: ignore[reportMissingImports]  # optional: resaid[database]
            if not jpype.isJVMStarted():
                # Try to start JVM and load UCanAccess
                jpype.startJVM()
            
            # This would require UCanAccess JAR files
            # For now, return False
            return False
        except Exception:  # noqa: BLE001 - JPype/JVM failures mean not connected
            return False
    
    def _try_phdwin_connection(self) -> bool:
        """Try to establish connection using pytopspeed-modernized for PhdWin files"""
        try:
            import sqlite3
            import tempfile
            
            # Convert PhdWin file to temporary SQLite database
            with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as temp_db:
                temp_db_path = temp_db.name
            
            # Use appropriate converter based on file extension
            file_ext = self.db_path.suffix.lower()
            
            if file_ext == '.phz':
                # Use PhzConverter for .phz files (zip archives)
                from converter.phz_converter import PhzConverter  # pyright: ignore[reportMissingImports]  # optional: resaid[database]
                converter = PhzConverter()
                result = converter.convert_phz(str(self.db_path), temp_db_path)
            else:
                # Use SqliteConverter for .phd, .mod, .tps files
                from converter.sqlite_converter import SqliteConverter  # pyright: ignore[reportMissingImports]  # optional: resaid[database]
                converter = SqliteConverter()
                result = converter.convert(str(self.db_path), temp_db_path)
            
            # Check if conversion was successful
            if not result.get('success', False):
                warnings.warn(f"PhdWin conversion failed: {result.get('errors', ['Unknown error'])}")
                return False
            
            # Connect to the temporary SQLite database
            self.connection = sqlite3.connect(temp_db_path)
            self._temp_db_path = temp_db_path  # Store for cleanup
            return True
            
        except ImportError:
            message = 'pytopspeed-modernized is not installed (pip install "resaid[database]")'
            self._connect_errors.append(message)
            warnings.warn(message)
            return False
        except Exception as e:  # noqa: BLE001 - any converter failure means not connected
            self._connect_errors.append(f"PhdWin conversion failed: {e}")
            warnings.warn(f"Failed to convert PhdWin database: {e}")
            return False
    
    def _try_external_tools(self) -> bool:
        """
        Check whether mdbtools can read the file.

        Returns True if ``mdb-tables`` succeeds, but does not open a connection, so
        ``connect()`` does not count it as connected.
        """
        try:
            # Try mdbtools if available
            result = subprocess.run(['mdb-tables', str(self.db_path)], 
                                  capture_output=True, text=True, timeout=30, check=False)
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        try:
            # Try alternative mdb tools
            result = subprocess.run(['mdbtools', str(self.db_path)], 
                                  capture_output=True, text=True, timeout=30, check=False)
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        return False
    
    def connect(self) -> bool:
        """
        Attempt to connect to the database using available methods
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        # Try different connection methods based on database type
        if self.db_type == 'access':
            methods = [
                self._try_pyodbc_connection,
                self._try_jpype_connection,
                self._try_external_tools
            ]
        elif self.db_type == 'phdwin':
            methods = [
                self._try_phdwin_connection
            ]
        else:
            return False

        self._connect_errors = []
        for method in methods:
            # A method can report success without opening a usable connection
            # (e.g. the mdbtools probe); only an actual connection counts.
            if method() and self.connection is not None:
                return True

        return False

    def _require_connection(self) -> Any:
        """
        Return an open connection, connecting first if needed.

        Raises:
            ConnectionError: With the reasons each connection method failed.
        """
        if self.connection is None and not self.connect():
            reasons = "; ".join(self._connect_errors) or "no connection method succeeded"
            raise ConnectionError(f"Could not connect to {self.db_path}: {reasons}")
        if self.connection is None:
            raise ConnectionError(f"Could not connect to {self.db_path}")
        return self.connection
    
    def get_tables(self) -> list[str]:
        """Get list of available tables"""
        connection = self._require_connection()

        try:
            cursor = connection.cursor()
            if isinstance(connection, sqlite3.Connection):
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                return [row[0] for row in cursor.fetchall()]
            return [table.table_name for table in cursor.tables(tableType='TABLE')]
        except Exception as e:  # noqa: BLE001 - driver-specific errors; report and return none
            warnings.warn(f"Could not get tables: {e}")
            return []
    
    def get_table_columns(self, table_name: str) -> list[str]:
        """Get column names for a specific table"""
        connection = self._require_connection()

        try:
            cursor = connection.cursor()
            if isinstance(connection, sqlite3.Connection):
                cursor.execute(f'PRAGMA table_info("{table_name}")')
                return [row[1] for row in cursor.fetchall()]
            return [column.column_name for column in cursor.columns(table=table_name)]
        except Exception as e:  # noqa: BLE001 - driver-specific errors; report and return none
            warnings.warn(f"Could not get columns for table {table_name}: {e}")
            return []
    
    def set_table_mapping(self, mapping: dict[str, str]):
        """
        Set table mapping for different data types
        
        Args:
            mapping: Dictionary mapping table types to actual table names
                    Example: {
                        'production': 'AC_PRODUCT',
                        'header': 'AC_PROPERTY',
                        'well': 'AC_WELL'
                    }
        """
        self.table_mapping = mapping
    
    def set_column_mapping(self, mapping: dict[str, str]):
        """
        Set column mapping for database fields to RESAID fields
        
        Args:
            mapping: Dictionary mapping RESAID field names to database column names
                    Required: 'well_id', 'date', 'oil', 'gas', 'water'
                    Example: {
                        'well_id': 'PROPNUM',
                        'date': 'P_DATE', 
                        'oil': 'OIL',
                        'gas': 'GAS',
                        'water': 'WATER'
                    }
        """
        self.column_mapping = mapping
    
    def set_header_column_mapping(self, mapping: dict[str, str]):
        """
        Set header column mapping for well-level properties
        
        Args:
            mapping: Dictionary mapping RESAID field names to header table column names.
                    Supported fields: 'well_id', 'phase', 'length', 'dayson', 'field',
                    'operator'. Include only fields whose columns exist: every mapped
                    column is selected, and a missing one makes the read fail.
                    Example: {
                        'well_id': 'PROPNUM',
                        'phase': 'MAJOR',
                        'length': 'LATERAL',
                        'dayson': 'DAYS_ON',
                        'field': 'FIELD',
                        'operator': 'OPERATOR'
                    }
        """
        self.header_column_mapping = mapping
        self._header_mapping_is_default = False
    
    def read_table_data(self,
                        table_name: str,
                        columns: list[str] | None = None,
                        parse_dates: bool = True) -> pd.DataFrame:
        """
        Read data from a specific table
        
        Table and column names are bracket-quoted, so names with spaces or reserved
        words (e.g. ``DATE``) work in both Access and SQLite.
        
        Args:
            table_name: Name of the table to read
            columns: Optional list of specific columns to read (None = all columns)
            parse_dates: Convert columns whose name contains ``DATE`` or ``PROD`` to
                datetimes (best effort). ``prepare_data_for_dca`` turns this off and
                converts only the mapped date column.
            
        Returns:
            DataFrame with table data; column names upper-cased
        """
        connection = self._require_connection()

        try:
            if columns:
                columns_str = ', '.join(f"[{col}]" for col in columns)
                query = f"SELECT {columns_str} FROM [{table_name}]"
            else:
                query = f"SELECT * FROM [{table_name}]"
            
            with warnings.catch_warnings():
                # pandas warns for any non-SQLAlchemy DBAPI connection (pyodbc); harmless here.
                warnings.filterwarnings(
                    "ignore", message="pandas only supports SQLAlchemy connectable", category=UserWarning
                )
                df = pd.read_sql(query, connection)
            
            # Standardize column names
            df.columns = [col.upper() for col in df.columns]
            
            # Convert date columns automatically
            date_columns = (
                [col for col in df.columns if 'DATE' in col or 'PROD' in col]
                if parse_dates else []
            )
            for col in date_columns:
                try:
                    df[col] = pd.to_datetime(df[col])
                except (ValueError, TypeError, OverflowError):
                    pass  # not a date column; leave as read
            
            return df
            
        except Exception as e:
            raise RuntimeError(f"Could not read data from table {table_name}: {e}") from e
    
    def _resolve_columns(self,
                         table_name: str,
                         mapping: dict[str, str],
                         required_fields: list[str],
                         skip_missing_optional: bool = False,
                         argument_name: str = "columns") -> dict[str, str]:
        """
        Match a RESAID field -> column mapping against the table's actual columns.

        Columns are matched case-insensitively and returned with the table's own
        spelling. Missing required fields, or missing optional fields when
        ``skip_missing_optional`` is False, raise ``ValueError`` naming the missing
        columns and listing the available ones. With ``skip_missing_optional`` True,
        missing optional fields are dropped with a warning.

        If the table's columns cannot be listed, the mapping is returned unchanged
        and any error surfaces from the query itself.
        """
        unmapped = [f for f in required_fields if not mapping.get(f)]
        if unmapped:
            raise ValueError(
                f"{argument_name} for {table_name} must map {unmapped} to columns"
            )

        available = self.get_table_columns(table_name)
        if not available:
            return {field: col for field, col in mapping.items() if col}
        by_upper = {col.upper(): col for col in available}

        resolved = {}
        missing = []
        skipped = []
        for field, col in mapping.items():
            if not col:
                continue
            actual = by_upper.get(str(col).upper())
            if actual is not None:
                resolved[field] = actual
            elif skip_missing_optional and field not in required_fields:
                skipped.append(f"{col} ({field})")
            else:
                missing.append(f"{col} ({field})")

        if missing:
            raise ValueError(
                f"Table {table_name} has no column(s): {', '.join(missing)}. "
                f"Available columns: {', '.join(available)}. "
                f"Pass {argument_name}={{field: column, ...}} to map them."
            )
        if skipped:
            warnings.warn(
                f"Table {table_name} has no column(s) {', '.join(skipped)} from the default "
                f"mapping; skipping them. Pass {argument_name} to map these fields.",
                stacklevel=3,
            )
        return resolved

    def prepare_data_for_dca(self,
                            production_table: str,
                            production_columns: dict[str, str],
                            header_table: str | None = None,
                            header_columns: dict[str, str] | None = None,
                            skip_missing_header_columns: bool = False,
                            **kwargs) -> pd.DataFrame:
        """
        Prepare data for DCA analysis using flexible table and column mapping

        Mapped columns are checked against each table before reading (names match
        case-insensitively). Production fields are all required. Header fields other
        than 'well_id' are optional, but a mapped header column that does not exist
        raises unless ``skip_missing_header_columns`` is True.

        Args:
            production_table: Name of production data table
            production_columns: Dictionary mapping RESAID fields to production table columns
                               Required: 'well_id', 'date', 'oil', 'gas', 'water'
            header_table: Optional name of header data table
            header_columns: Optional dictionary mapping RESAID fields to header table
                columns ('well_id' required; 'phase', 'length', 'dayson', 'field',
                'operator' optional). Pass an empty dict to skip the header read.
            skip_missing_header_columns: Drop mapped header columns that the table
                lacks (with a warning) instead of raising.
            **kwargs: Accepted for compatibility; unused

        Returns:
            DataFrame with columns WELL_ID, DATE, OIL, GAS, WATER plus the upper-cased
            names of mapped header fields (PHASE, LENGTH, DAYSON, FIELD, OPERATOR),
            sorted by WELL_ID and DATE

        Raises:
            ValueError: If a required field is unmapped or a mapped column is missing.
        """
        required_prod_fields = ['well_id', 'date', 'oil', 'gas', 'water']
        prod_map = self._resolve_columns(
            production_table, production_columns, required_prod_fields,
            argument_name="production_columns",
        )

        print(f"Reading production data from {production_table} with columns: {list(prod_map.values())}")
        production = self.read_table_data(
            production_table, columns=list(prod_map.values()), parse_dates=False
        )
        production = production.rename(
            columns={col.upper(): field.upper() for field, col in prod_map.items()}
        )
        production['DATE'] = pd.to_datetime(production['DATE'])
        print(f"Production data loaded: {production.shape}")
        self._production_data = production

        merged = production
        if header_table and header_columns:
            header_map = self._resolve_columns(
                header_table, header_columns, ['well_id'],
                skip_missing_optional=skip_missing_header_columns,
                argument_name="header_columns",
            )
            print(f"Reading header data from {header_table} with columns: {list(header_map.values())}")
            header = self.read_table_data(
                header_table, columns=list(header_map.values()), parse_dates=False
            )
            header = header.rename(
                columns={col.upper(): field.upper() for field, col in header_map.items()}
            )
            print(f"Header data loaded: {header.shape}")

            dup = header['WELL_ID'].duplicated()
            if dup.any():
                warnings.warn(
                    f"{int(dup.sum())} duplicate well IDs in {header_table}; "
                    "using the first row for each",
                    stacklevel=2,
                )
                header = header[~dup]
            self._header_data = header

            # Production columns win if a header field has the same name.
            header = header.drop(
                columns=[c for c in header.columns if c != 'WELL_ID' and c in production.columns]
            )
            unmatched = set(production['WELL_ID']) - set(header['WELL_ID'])
            if unmatched:
                warnings.warn(
                    f"{len(unmatched)} wells in {production_table} have no row in {header_table}",
                    stacklevel=2,
                )
            merged = production.merge(header, on='WELL_ID', how='left')
            print(f"Data merged: {merged.shape}")

        return merged.sort_values(['WELL_ID', 'DATE']).reset_index(drop=True)

    def run_dca_analysis(self, 
                         data: pd.DataFrame,
                         three_phase_mode: bool = True,
                         **dca_kwargs) -> dict[str, decline_curve]:
        """
        Run DCA analysis on prepared data
        
        Args:
            data: DataFrame with production data
            three_phase_mode: Whether to use three-phase forecasting
            **dca_kwargs: Accepted for compatibility; currently unused
            
        Returns:
            Dictionary mapping well IDs to decline_curve objects. Each has been run
            and has a oneline (not denormalized). Wells with fewer than 3 rows are
            skipped with a warning.
        """
        results = {}
        
        for well_id in data['WELL_ID'].unique():
            well_data = data[data['WELL_ID'] == well_id].copy()
            
            if len(well_data) < 3:  # Need at least 3 data points
                warnings.warn(f"Insufficient data for well {well_id}, skipping")
                continue
            
            try:
                # Create decline curve object
                dca = decline_curve()
                
                # Set three-phase mode if specified
                if hasattr(dca, 'three_phase_mode'):
                    dca.three_phase_mode = three_phase_mode
                
                # Set data
                dca.dataframe = well_data
                
                # Set column names (use standard RESAID column names)
                dca.date_col = 'DATE'
                dca.uid_col = 'WELL_ID'
                dca.oil_col = 'OIL'
                dca.gas_col = 'GAS'
                dca.water_col = 'WATER'
                
                # Set optional columns if they exist. A header phase is used only
                # when it is OIL or GAS; otherwise the GOR classification applies.
                if 'PHASE' in well_data.columns:
                    phase = well_data['PHASE'].astype(str).str.strip().str.upper()
                    if phase.isin(['OIL', 'GAS']).all():
                        well_data['PHASE'] = phase
                        dca.phase_col = 'PHASE'
                    else:
                        warnings.warn(
                            f"Well {well_id}: header phase {sorted(phase.unique())} is not "
                            "OIL or GAS; classifying by GOR instead"
                        )
                if 'LENGTH' in well_data.columns:
                    well_data['LENGTH'] = pd.to_numeric(well_data['LENGTH'], errors='coerce')
                    dca.length_col = 'LENGTH'
                if 'DAYSON' in well_data.columns:
                    well_data['DAYSON'] = pd.to_numeric(well_data['DAYSON'], errors='coerce')
                    dca.dayson_col = 'DAYSON'
                
                # Run DCA
                dca.run_DCA()
                dca.generate_oneline()
                
                results[well_id] = dca
                
            except Exception as e:  # noqa: BLE001 - one well's failure must not stop the batch
                warnings.warn(f"Failed to run DCA for well {well_id}: {e}")
                warnings.warn(f"Traceback: {traceback.format_exc()}")
                continue
        
        return results
    
    def export_results(self, 
                      dca_results: dict[str, decline_curve],
                      export_format: str = 'aries',
                      output_dir: str | Path | None = None) -> dict[str, str]:
        """
        Export DCA results in specified format
        
        Args:
            dca_results: Dictionary of DCA results
            export_format: Export format ('aries' or 'mosaic'). 'phdwin' is
                accepted but currently fails for every well (a warning is issued
                and the well is omitted from the result).
            output_dir: Output directory (defaults to current directory)
            
        Returns:
            Dictionary mapping well IDs to output file paths. Failures, including an
            unsupported format, are reported as warnings, not raised.
        """
        if output_dir is None:
            output_dir = Path.cwd()
        else:
            output_dir = Path(output_dir)
            output_dir.mkdir(exist_ok=True)
        
        output_files = {}
        
        for well_id, dca_obj in dca_results.items():
            try:
                # Generate export based on format
                if export_format == 'aries':
                    output_file = output_dir / f"{well_id}_aries_export.txt"
                    # Call the existing generate_aries_export method
                    dca_obj.generate_aries_export(str(output_file))
                    
                elif export_format == 'phdwin':
                    output_file = output_dir / f"{well_id}_phdwin_export.csv"
                    # Call the existing generate_phdwin_export method
                    output_df = dca_obj.generate_phdwin_export()
                    output_df.to_csv(output_file, index=False)
                    
                elif export_format == 'mosaic':
                    output_file = output_dir / f"{well_id}_mosaic_export.xlsx"
                    # Call the existing generate_mosaic_export method
                    dca_obj.generate_mosaic_export(str(output_file))
                    
                else:
                    raise ValueError(f"Unsupported export format: {export_format}")
                
                output_files[well_id] = str(output_file)
                
            except Exception as e:  # noqa: BLE001 - one well's failure must not stop the batch
                warnings.warn(f"Failed to export {export_format} for well {well_id}: {e}")
                continue
        
        return output_files
    
    def close(self):
        """Close database connection"""
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                logger.debug("Error closing database connection", exc_info=True)
            self.connection = None
        
        # Clean up temporary database file if it exists
        if hasattr(self, '_temp_db_path') and self._temp_db_path:
            try:
                os.unlink(self._temp_db_path)
            except OSError:
                logger.debug("Could not remove %s", self._temp_db_path, exc_info=True)
            self._temp_db_path = None
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()


# ARIES table and column names used as defaults by ARIESDatabase (and PhdWinDatabase).
ARIES_DEFAULT_TABLES = {
    'production': 'AC_PRODUCT',
    'header': 'AC_PROPERTY',
    'well': 'AC_WELL',
}
ARIES_DEFAULT_PRODUCTION_COLUMNS = {
    'well_id': 'PROPNUM',
    'date': 'P_DATE',
    'oil': 'OIL',
    'gas': 'GAS',
    'water': 'WATER',
}
# AC_PROPERTY fields are user-defined in ARIES, so these are guesses; any that a
# database lacks are skipped with a warning while this default is in use.
ARIES_DEFAULT_HEADER_COLUMNS = {
    'well_id': 'PROPNUM',
    'phase': 'MAJOR',
    'length': 'LATERAL',
    'dayson': 'DAYS_ON',
    'field': 'FIELD',
    'operator': 'OPERATOR',
}


class _DefaultMappedDatabase(DatabaseInterface):
    """
    Database with default table and column mappings.

    Mappings come from, in order: arguments to ``prepare_data_for_dca``, then
    ``set_table_mapping`` / ``set_column_mapping`` / ``set_header_column_mapping``,
    then the built-in ARIES defaults.
    """

    def __init__(self, db_path: str | Path):
        super().__init__(db_path)
        self.set_table_mapping(dict(ARIES_DEFAULT_TABLES))
        self.set_column_mapping(dict(ARIES_DEFAULT_PRODUCTION_COLUMNS))
        self.set_header_column_mapping(dict(ARIES_DEFAULT_HEADER_COLUMNS))
        self._header_mapping_is_default = True

    def prepare_data_for_dca(self,
                            production_table: str | None = None,
                            production_columns: dict[str, str] | None = None,
                            header_table: str | None = None,
                            header_columns: dict[str, str] | None = None,
                            skip_missing_header_columns: bool | None = None,
                            **kwargs) -> pd.DataFrame:
        """
        Prepare data for DCA analysis, filling unspecified tables and columns from
        the instance mappings.

        Args:
            production_table: Production table name (default from ``set_table_mapping``)
            production_columns: Full production column mapping; all of 'well_id',
                'date', 'oil', 'gas', 'water' are required
            header_table: Header table name (default from ``set_table_mapping``)
            header_columns: Full header column mapping ('well_id' required; 'phase',
                'length', 'dayson', 'field', 'operator' optional), or {} to skip the
                header read
            skip_missing_header_columns: Skip mapped header columns the table lacks
                instead of raising. Defaults to True only while the built-in default
                header mapping is in use, and False for a mapping you supplied.
            **kwargs: Accepted for compatibility; unused

        Returns:
            DataFrame with WELL_ID, DATE, OIL, GAS, WATER and any mapped header fields

        Raises:
            ValueError: If a mapped column does not exist (the message lists the
                table's columns).
        """
        if production_table is None:
            production_table = self.table_mapping.get('production', ARIES_DEFAULT_TABLES['production'])
        if production_columns is None:
            production_columns = dict(self.column_mapping)
        if header_table is None:
            header_table = self.table_mapping.get('header', ARIES_DEFAULT_TABLES['header'])

        header_is_default = header_columns is None and self._header_mapping_is_default
        if header_columns is None:
            header_columns = dict(self.header_column_mapping)
        if skip_missing_header_columns is None:
            skip_missing_header_columns = header_is_default

        return super().prepare_data_for_dca(
            production_table=production_table,
            production_columns=production_columns,
            header_table=header_table,
            header_columns=header_columns,
            skip_missing_header_columns=skip_missing_header_columns,
            **kwargs
        )


class ARIESDatabase(_DefaultMappedDatabase):
    """
    Interface for ARIES Access databases (.mdb/.accdb).

    Defaults read AC_PRODUCT (PROPNUM, P_DATE, OIL, GAS, WATER) and AC_PROPERTY
    (PROPNUM, MAJOR, LATERAL, DAYS_ON, FIELD, OPERATOR). AC_PROPERTY fields vary
    between databases; default header columns a database lacks are skipped with a
    warning. To use your own names, pass ``production_columns`` / ``header_columns``
    (and table names) to ``prepare_data_for_dca`` or set them once with
    ``set_table_mapping``, ``set_column_mapping`` and ``set_header_column_mapping``.
    """

    def __init__(self, db_path: str | Path):
        super().__init__(db_path)
        if self.db_type != 'access':
            raise ValueError("ARIES databases must be Access format (.mdb/.accdb)")


class PhdWinDatabase(_DefaultMappedDatabase):
    """
    Interface for PhdWin TopSpeed databases (experimental).

    The file is converted to a temporary SQLite database on connect. Its default
    table and column mappings are the ARIES ones, which converted PhdWin data does
    not contain, so pass ``production_table`` and ``production_columns`` (and
    ``header_columns={}`` or a valid header mapping) to ``prepare_data_for_dca``.
    The production table must have one row per well and date with oil, gas and
    water columns; PhdWin integer dates must be converted beforehand.
    """

    def __init__(self, db_path: str | Path):
        super().__init__(db_path)
        if self.db_type != 'phdwin':
            raise ValueError("PhdWin databases must be TopSpeed format (.phd/.mod/.tps/.phz)")
