#!/usr/bin/env python3
"""
Database interface for RESAID to read industry standard databases
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
from typing import Dict, List, Optional, Union, Tuple
import subprocess
import tempfile
import os

from .dca import decline_curve


class DatabaseInterface:
    """
    Flexible interface for reading industry standard databases and generating DCA forecasts
    
    Supports:
    - ARIES databases (.mdb, .accdb files) - Access format
    - PhdWin databases (.phd, .mod, .tps, .phz files) - TopSpeed format via pytopspeed-modernized
    - Future: Other database formats
    """
    
    def __init__(self, db_path: Union[str, Path]):
        """
        Initialize database interface
        
        Args:
            db_path: Path to database file
        """
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database file not found: {self.db_path}")
        
        self.db_type = self._detect_db_type()
        self.connection = None
        self._production_data = None
        self._header_data = None
        
        # Column mapping configuration - maps RESAID fields to database columns
        self.column_mapping = {}
        
        # Table configuration - maps table types to actual table names
        self.table_mapping = {}
        
    def _detect_db_type(self) -> str:
        """Detect database type based on file extension and content"""
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
            import pyodbc
            conn_str = f"Driver={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={self.db_path.absolute()}"
            self.connection = pyodbc.connect(conn_str)
            return True
        except (ImportError, Exception):
            return False
    
    def _try_jpype_connection(self) -> bool:
        """Try to establish connection using JPype and Java libraries"""
        try:
            import jpype
            if not jpype.isJVMStarted():
                # Try to start JVM and load UCanAccess
                jpype.startJVM()
            
            # This would require UCanAccess JAR files
            # For now, return False
            return False
        except Exception:
            return False
    
    def _try_phdwin_connection(self) -> bool:
        """Try to establish connection using pytopspeed-modernized for PhdWin files"""
        try:
            import tempfile
            import sqlite3
            
            # Convert PhdWin file to temporary SQLite database
            with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as temp_db:
                temp_db_path = temp_db.name
            
            # Use appropriate converter based on file extension
            file_ext = self.db_path.suffix.lower()
            
            if file_ext == '.phz':
                # Use PhzConverter for .phz files (zip archives)
                from converter.phz_converter import PhzConverter
                converter = PhzConverter()
                result = converter.convert_phz(str(self.db_path), temp_db_path)
            else:
                # Use SqliteConverter for .phd, .mod, .tps files
                from converter.sqlite_converter import SqliteConverter
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
            warnings.warn("pytopspeed-modernized not available. Install with: pip install pytopspeed-modernized")
            return False
        except Exception as e:
            warnings.warn(f"Failed to convert PhdWin database: {e}")
            return False
    
    def _try_external_tools(self) -> bool:
        """Try to use external tools like mdbtools or mdb-tools"""
        try:
            # Try mdbtools if available
            result = subprocess.run(['mdb-tables', str(self.db_path)], 
                                  capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        try:
            # Try alternative mdb tools
            result = subprocess.run(['mdbtools', str(self.db_path)], 
                                  capture_output=True, text=True, timeout=30)
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
        
        for method in methods:
            if method():
                return True
        
        return False
    
    def get_tables(self) -> List[str]:
        """Get list of available tables"""
        if not self.connection:
            if not self.connect():
                raise ConnectionError("Could not connect to database")
        
        try:
            if self.db_type == 'access':
                import pyodbc
                cursor = self.connection.cursor()
                tables = [table.table_name for table in cursor.tables(tableType='TABLE')]
                return tables
            elif self.db_type == 'phdwin':
                # SQLite connection
                cursor = self.connection.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                return tables
        except Exception as e:
            warnings.warn(f"Could not get tables: {e}")
            return []
    
    def get_table_columns(self, table_name: str) -> List[str]:
        """Get column names for a specific table"""
        if not self.connection:
            if not self.connect():
                raise ConnectionError("Could not connect to database")
        
        try:
            if self.db_type == 'access':
                import pyodbc
                cursor = self.connection.cursor()
                columns = [column.column_name for column in cursor.columns(table=table_name)]
                return columns
            elif self.db_type == 'phdwin':
                # SQLite connection
                cursor = self.connection.cursor()
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = [row[1] for row in cursor.fetchall()]
                return columns
        except Exception as e:
            warnings.warn(f"Could not get columns for table {table_name}: {e}")
            return []
    
    def set_table_mapping(self, mapping: Dict[str, str]):
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
    
    def set_column_mapping(self, mapping: Dict[str, str]):
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
    
    def set_header_column_mapping(self, mapping: Dict[str, str]):
        """
        Set header column mapping for well-level properties
        
        Args:
            mapping: Dictionary mapping RESAID field names to header table column names
                    Optional: 'well_id', 'phase', 'length', 'dayson', 'field', 'operator'
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
    
    def read_table_data(self, table_name: str, columns: Optional[List[str]] = None) -> pd.DataFrame:
        """
        Read data from a specific table
        
        Args:
            table_name: Name of the table to read
            columns: Optional list of specific columns to read (None = all columns)
            
        Returns:
            DataFrame with table data
        """
        if not self.connection:
            if not self.connect():
                raise ConnectionError("Could not connect to database")
        
        try:
            if columns:
                columns_str = ', '.join(columns)
                query = f"SELECT {columns_str} FROM {table_name}"
            else:
                query = f"SELECT * FROM {table_name}"
            
            df = pd.read_sql(query, self.connection)
            
            # Standardize column names
            df.columns = [col.upper() for col in df.columns]
            
            # Convert date columns automatically
            date_columns = [col for col in df.columns if 'DATE' in col or 'PROD' in col]
            for col in date_columns:
                try:
                    df[col] = pd.to_datetime(df[col])
                except:
                    pass
            
            return df
            
        except Exception as e:
            raise RuntimeError(f"Could not read data from table {table_name}: {e}")
    
    def prepare_data_for_dca(self, 
                            production_table: str,
                            production_columns: Dict[str, str],
                            header_table: Optional[str] = None,
                            header_columns: Optional[Dict[str, str]] = None,
                            **kwargs) -> pd.DataFrame:
        """
        Prepare data for DCA analysis using flexible table and column mapping
        
        Args:
            production_table: Name of production data table
            production_columns: Dictionary mapping RESAID fields to production table columns
                               Required: 'well_id', 'date', 'oil', 'gas', 'water'
            header_table: Optional name of header data table
            header_columns: Optional dictionary mapping RESAID fields to header table columns
            **kwargs: Additional arguments for data preparation
            
        Returns:
            DataFrame ready for DCA analysis
        """
        # Validate required production columns
        required_prod_fields = ['well_id', 'date', 'oil', 'gas', 'water']
        missing_prod_fields = [field for field in required_prod_fields if field not in production_columns]
        if missing_prod_fields:
            raise ValueError(f"Missing required production fields: {missing_prod_fields}")
        
        # Read production data with specified columns
        prod_cols = list(production_columns.values())
        print(f"Reading production data from {production_table} with columns: {prod_cols}")
        self._production_data = self.read_table_data(production_table, columns=prod_cols)
        print(f"Production data loaded: {self._production_data.shape}")
        
        # Rename production columns to RESAID standard
        prod_rename = {v.upper(): k.upper() for k, v in production_columns.items()}
        self._production_data = self._production_data.rename(columns=prod_rename)
        
        # Read header data if specified
        if header_table and header_columns:
            print(f"Reading header data from {header_table} with columns: {list(header_columns.values())}")
            header_cols = list(header_columns.values())
            self._header_data = self.read_table_data(header_table, columns=header_cols)
            print(f"Header data loaded: {self._header_data.shape}")
            
            # Rename header columns to RESAID standard
            header_rename = {v.upper(): k.upper() for k, v in header_columns.items()}
            self._header_data = self._header_data.rename(columns=header_rename)
            
            # Merge production and header data
            merge_key = production_columns['well_id'].upper()
            if merge_key in self._production_data.columns and merge_key in self._header_data.columns:
                merged = pd.merge(
                    self._production_data,
                    self._header_data,
                    on=merge_key,
                    how='left'
                )
                print(f"Data merged: {merged.shape}")
            else:
                print(f"Warning: Merge key '{merge_key}' not found in both tables")
                merged = self._production_data
        else:
            merged = self._production_data
        
        # Ensure required columns exist after renaming
        required_cols = ['WELL_ID', 'DATE', 'OIL', 'GAS', 'WATER']
        missing_cols = [col for col in required_cols if col not in merged.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns after mapping: {missing_cols}")
        
        # Sort by well and date
        merged = merged.sort_values(['WELL_ID', 'DATE'])
        
        return merged
    
    def run_dca_analysis(self, 
                         data: pd.DataFrame,
                         three_phase_mode: bool = True,
                         **dca_kwargs) -> Dict[str, decline_curve]:
        """
        Run DCA analysis on prepared data
        
        Args:
            data: DataFrame with production data
            three_phase_mode: Whether to use three-phase forecasting
            **dca_kwargs: Additional arguments for decline_curve
            
        Returns:
            Dictionary mapping well IDs to decline_curve objects
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
                
                # Set optional columns if they exist
                if 'PHASE' in well_data.columns:
                    dca.phase_col = 'PHASE'
                if 'LENGTH' in well_data.columns:
                    dca.length_col = 'LENGTH'
                if 'DAYSON' in well_data.columns:
                    dca.dayson_col = 'DAYSON'
                
                # Run DCA
                dca.run_DCA()
                dca.generate_oneline()
                
                results[well_id] = dca
                
            except Exception as e:
                warnings.warn(f"Failed to run DCA for well {well_id}: {e}")
                import traceback
                warnings.warn(f"Traceback: {traceback.format_exc()}")
                continue
        
        return results
    
    def export_results(self, 
                      dca_results: Dict[str, decline_curve],
                      export_format: str = 'aries',
                      output_dir: Optional[Union[str, Path]] = None) -> Dict[str, str]:
        """
        Export DCA results in specified format
        
        Args:
            dca_results: Dictionary of DCA results
            export_format: Export format ('aries', 'phdwin', 'mosaic')
            output_dir: Output directory (defaults to current directory)
            
        Returns:
            Dictionary mapping well IDs to output file paths
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
                
            except Exception as e:
                warnings.warn(f"Failed to export {export_format} for well {well_id}: {e}")
                continue
        
        return output_files
    
    def close(self):
        """Close database connection"""
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
            self.connection = None
        
        # Clean up temporary database file if it exists
        if hasattr(self, '_temp_db_path') and self._temp_db_path:
            try:
                os.unlink(self._temp_db_path)
            except:
                pass
            self._temp_db_path = None
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()


class ARIESDatabase(DatabaseInterface):
    """Specialized interface for ARIES databases with common defaults"""
    
    def __init__(self, db_path: Union[str, Path]):
        super().__init__(db_path)
        if self.db_type != 'access':
            raise ValueError("ARIES databases must be Access format (.mdb/.accdb)")
        
        # Set common ARIES table mappings as defaults
        self.set_table_mapping({
            'production': 'AC_PRODUCT',
            'header': 'AC_PROPERTY',
            'well': 'AC_WELL'
        })
        
        # Set production column mappings (from AC_PRODUCT table)
        self.set_column_mapping({
            'well_id': 'PROPNUM',
            'date': 'P_DATE',
            'oil': 'OIL',
            'gas': 'GAS',
            'water': 'WATER'
        })
        
        # Set header column mappings (from AC_PROPERTY table)
        self.set_header_column_mapping({
            'well_id': 'PROPNUM',
            'phase': 'MAJOR',
            'length': 'LATERAL',
            'dayson': 'DAYS_ON',
            'field': 'FIELD',
            'operator': 'OPERATOR'
        })
    
    def prepare_data_for_dca(self, 
                            production_table: Optional[str] = None,
                            production_columns: Optional[Dict[str, str]] = None,
                            header_table: Optional[str] = None,
                            header_columns: Optional[Dict[str, str]] = None,
                            **kwargs) -> pd.DataFrame:
        """
        Prepare ARIES data for DCA analysis with common defaults
        
        Args:
            production_table: Override default production table name
            production_columns: Override default production column mapping
            header_table: Override default header table name  
            header_columns: Override default header column mapping
            **kwargs: Additional arguments
        """
        # Use defaults if not specified
        if production_table is None:
            production_table = self.table_mapping.get('production', 'AC_PRODUCT')
        
        if production_columns is None:
            production_columns = self.column_mapping.copy()
        
        if header_table is None:
            header_table = self.table_mapping.get('header', 'AC_PROPERTY')
        
        if header_columns is None:
            header_columns = self.header_column_mapping.copy()
        
        return super().prepare_data_for_dca(
            production_table=production_table,
            production_columns=production_columns,
            header_table=header_table,
            header_columns=header_columns,
            **kwargs
        )


class PhdWinDatabase(DatabaseInterface):
    """Specialized interface for PhdWin databases"""
    
    def __init__(self, db_path: Union[str, Path]):
        super().__init__(db_path)
        if self.db_type != 'phdwin':
            raise ValueError("PhdWin databases must be TopSpeed format (.phd/.mod/.tps/.phz)")
        
        # Set common PhdWin table mappings as defaults
        # Note: These will be determined after conversion to SQLite
        self.set_table_mapping({
            'production': 'AC_PRODUCT',  # Default, may be overridden
            'header': 'AC_PROPERTY',     # Default, may be overridden
            'well': 'AC_WELL'           # Default, may be overridden
        })
        
        # Set production column mappings (from AC_PRODUCT table)
        self.set_column_mapping({
            'well_id': 'PROPNUM',
            'date': 'P_DATE',
            'oil': 'OIL',
            'gas': 'GAS',
            'water': 'WATER'
        })
        
        # Set header column mappings (from AC_PROPERTY table)
        self.set_header_column_mapping({
            'well_id': 'PROPNUM',
            'phase': 'MAJOR',
            'length': 'LATERAL',
            'dayson': 'DAYS_ON',
            'field': 'FIELD',
            'operator': 'OPERATOR'
        })
    
    def prepare_data_for_dca(self, 
                            production_table: Optional[str] = None,
                            production_columns: Optional[Dict[str, str]] = None,
                            header_table: Optional[str] = None,
                            header_columns: Optional[Dict[str, str]] = None,
                            **kwargs) -> pd.DataFrame:
        """
        Prepare PhdWin data for DCA analysis with common defaults
        
        Args:
            production_table: Override default production table name
            production_columns: Override default production column mapping
            header_table: Override default header table name  
            header_columns: Override default header column mapping
            **kwargs: Additional arguments
        """
        # Use defaults if not specified
        if production_table is None:
            production_table = self.table_mapping.get('production', 'AC_PRODUCT')
        
        if production_columns is None:
            production_columns = self.column_mapping.copy()
        
        if header_table is None:
            header_table = self.table_mapping.get('header', 'AC_PROPERTY')
        
        if header_columns is None:
            header_columns = self.header_column_mapping.copy()
        
        return super().prepare_data_for_dca(
            production_table=production_table,
            production_columns=production_columns,
            header_table=header_table,
            header_columns=header_columns,
            **kwargs
        )

