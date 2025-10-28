# PhdWin Database Relationships Analysis (Final - Updated)

This document provides an analysis of the key relationships between tables in the PhdWin database based on the latest pytopspeed-modernized 1.1.3 conversion.

## Database Overview

- **Total Tables**: 76
- **Total Records**: 14,756
- **PhdWin Database Tables (phd_)**: 55 tables
- **Model Tables (mod_)**: 21 tables

## Date Format for Integration

PhdWin uses a custom date encoding system where dates are stored as integers representing **days since December 28, 1800**.

### Date Conversion Function

```python
def convert_phdwin_date(phd_date):
    """Convert PhdWin date integer to actual date"""
    from datetime import datetime, timedelta
    epoch = datetime(1800, 12, 28)
    return epoch + timedelta(days=phd_date)
```

### Key Date Fields for DCA

- **phd_DAILY.TDATE** - Daily production dates
- **phd_CATEGORY.TDATE** - Category dates
- **phd_PHDCASECHANGE.CHANGEDATE** - Case change dates
- **phd_OWNER.RESOLVEDDATE** - Ownership resolution dates
- **phd_INVEST.HARDDATE** - Investment dates

## Primary Entity Structure

### Central Entity: LSE_ID (Lease/Well ID)

The **LSE_ID** serves as the primary entity identifier throughout the PhdWin database, similar to how **AC_PRODUCT** and **AC_PROPERTY** work in ARIES databases.

### Core Production Tables

1. **phd_FORCAST** (4,370 records) ⭐ **PRIMARY PRODUCTION DATA**
   - **Purpose**: Forecast and production data - appears to be the main production table
   - **Key Fields**: Production forecast data and historical values
   - **Relationship**: Links to LSE_ID for well identification
   - **Importance**: This is now the largest production data table with 4,370 records

2. **phd_LSEPRODVAL** (1,330 records) ⭐ **SECONDARY PRODUCTION DATA**
   - **Purpose**: Lease production values and historical data
   - **Key Fields**: LSE_ID, PRODUCTCODE, YEAR, MONTHVAL, VALUE
   - **Relationship**: Links to LSE_ID for well identification
   - **Importance**: Secondary production data table

3. **phd_LSESEGMENT** (475 records) ⭐ **PRODUCTION SEGMENTS**
   - **Purpose**: Production segments and time periods
   - **Key Fields**: LSE_ID, SEGMENT, STARTDATE, ENDDATE
   - **Relationship**: Links to LSE_ID for well identification

4. **phd_MONHIST** (313 records) ⭐ **MONTHLY HISTORY**
   - **Purpose**: Monthly production history
   - **Key Fields**: LSE_ID, YEAR, MONTH, PRODUCTION values
   - **Relationship**: Links to LSE_ID for well identification

5. **phd_DAILY** (4 records)
   - **Purpose**: Daily production data
   - **Key Fields**: LSE_ID, TDATE, MCFDAY, WATDAY, BBLDAY
   - **Relationship**: Links to LSE_ID for well identification

6. **phd_VOLUME** (95 records)
   - **Purpose**: Volume and reservoir data
   - **Key Fields**: LSE_ID, POROSITY, DRAINAREA, THICKNESS, GASULT, OILULT
   - **Relationship**: Links to LSE_ID for well identification

7. **phd_ZONE** (95 records)
   - **Purpose**: Zone and completion data
   - **Key Fields**: LSE_ID, TYPE, DESCR, LPERF, UPERF
   - **Relationship**: Links to LSE_ID for well identification

8. **phd_GRAPHS** (95 records) ⭐ **NEW - GRAPH DATA**
   - **Purpose**: Graph and visualization data
   - **Key Fields**: Graph-related data for wells
   - **Relationship**: Links to LSE_ID for well identification

### Economic and Ownership Tables

9. **phd_OWNER** (95 records)
   - **Purpose**: Ownership information
   - **Key Fields**: LSE_ID, GRP_ID, WRKINT, REVINT, NPINT
   - **Relationship**: Links to LSE_ID for well identification

10. **phd_INVEST** (95 records)
    - **Purpose**: Investment and CAPEX data
    - **Key Fields**: LSE_ID, GRP_ID, DESCR, INV_AMNT, INTANG_AMNT
    - **Relationship**: Links to LSE_ID for well identification

11. **phd_ECON** (0 records) ⭐ **NOTE: No data in this conversion**
    - **Purpose**: Economic parameters and calculations
    - **Key Fields**: LSE_ID, economic parameters, pricing data
    - **Relationship**: Links to LSE_ID for well identification

12. **phd_ROYALTY** (0 records)
    - **Purpose**: Royalty information
    - **Key Fields**: LSE_ID, GRP_ID, PERCENT, STARTDATE
    - **Relationship**: Links to LSE_ID for well identification

### Supporting Tables

13. **phd_PRODUCTNAMES** (56 records)
    - **Purpose**: Product type definitions
    - **Key Fields**: PRODUCTCODE, DESCR
    - **Relationship**: Referenced by other tables via PRODUCTCODE

14. **phd_CLASS** (3 records)
    - **Purpose**: Reserve class definitions
    - **Key Fields**: CLA_ID, NAME, SHORTNAME
    - **Relationship**: Referenced by other tables via CLA_ID

15. **phd_CATEGORY** (7 records)
    - **Purpose**: Well category definitions
    - **Key Fields**: CAT_ID, NAME, SHORTNAME
    - **Relationship**: Referenced by other tables via CAT_ID

### Model Tables (mod_) - Economic Modeling

The model tables contain economic modeling data and templates:

16. **mod_TEMPLATE** (33 records) ⭐ **NEW - TEMPLATE DATA**
    - **Purpose**: Economic model templates
    - **Key Fields**: TPL_ID, REGIME, CURRENCY
    - **Relationship**: Referenced by other model tables via TPL_ID

17. **mod_TPLPRODUCT** (322 records)
    - **Purpose**: Product model definitions
    - **Key Fields**: TPL_ID, TPF_ID, PRODUCTNAME
    - **Relationship**: Links to mod_TEMPLATE via TPL_ID

18. **mod_TPLPRODSEGMENT** (343 records)
    - **Purpose**: Production segment models
    - **Key Fields**: TPL_ID, TPF_ID, SEQ, VALUE
    - **Relationship**: Links to mod_TEMPLATE via TPL_ID

19. **mod_MODPRODVAL** (170 records) ⭐ **MODEL PRODUCTION VALUES**
    - **Purpose**: Model production values and forecasts
    - **Key Fields**: Model production data and forecasts
    - **Relationship**: Links to model templates

20. **mod_MODSEGMENT** (1,752 records) ⭐ **MODEL SEGMENTS**
    - **Purpose**: Model production segments
    - **Key Fields**: Model segment data and time periods
    - **Relationship**: Links to model templates

## Key Relationships for DCA Integration

### Primary Data Flow

```
LSE_ID (Central Entity)
├── phd_FORCAST (Primary Production Data) ⭐ NEW - 4,370 records
├── phd_LSEPRODVAL (Secondary Production Data) ⭐ 1,330 records
├── phd_LSESEGMENT (Production Segments) ⭐ 475 records
├── phd_MONHIST (Monthly History) ⭐ 313 records
├── phd_DAILY (Daily Production) - 4 records
├── phd_VOLUME (Reservoir Data) - 95 records
├── phd_ZONE (Completion Data) - 95 records
├── phd_GRAPHS (Graph Data) ⭐ NEW - 95 records
├── phd_OWNER (Ownership) - 95 records
├── phd_INVEST (CAPEX) - 95 records
└── phd_ROYALTY (Royalties) - 0 records
```

### Secondary Relationships

```
PRODUCTCODE
├── phd_PRODUCTNAMES (Product Definitions)
└── Referenced by production tables

CLA_ID
├── phd_CLASS (Reserve Class)
└── Referenced by economic tables

GRP_ID
├── phd_GROUPS (Group Definitions)
└── Referenced by ownership tables

TPL_ID (Model Templates)
├── mod_TEMPLATE (Template Definitions) ⭐ NEW - 33 records
├── mod_TPLPRODUCT (Product Models)
├── mod_TPLPRODSEGMENT (Segment Models)
├── mod_MODPRODVAL (Model Production Values) ⭐ 170 records
└── mod_MODSEGMENT (Model Segments) ⭐ 1,752 records
```

## Recommended DCA Integration Strategy

### Primary Production Data Sources (in order of importance):

1. **phd_FORCAST** ⭐ **PRIMARY** - Main production/forecast data table with 4,370 records
2. **phd_LSEPRODVAL** ⭐ **SECONDARY** - Secondary production data with 1,330 records
3. **phd_MONHIST** ⭐ **TERTIARY** - Monthly production history with 313 records
4. **phd_LSESEGMENT** ⭐ **SUPPORTING** - Production segments and time periods with 475 records
5. **phd_DAILY** - Daily production data with 4 records

### Header and Economic Data:

6. **phd_VOLUME** - Reservoir and ultimate recovery data (95 records)
7. **phd_ZONE** - Completion and zone data (95 records)
8. **phd_GRAPHS** ⭐ **NEW** - Graph and visualization data (95 records)
9. **phd_OWNER** - Ownership information (95 records)
10. **phd_INVEST** - CAPEX and investment data (95 records)
11. **phd_ECON** - Economic parameters (0 records in this conversion)

### Supporting Data:

12. **phd_PRODUCTNAMES** - Product type definitions (56 records)
13. **phd_CLASS** - Reserve class definitions (3 records)
14. **phd_CATEGORY** - Well category definitions (7 records)

## Table Mapping for RESAID Integration

### Production Data (Primary)
- **phd_FORCAST** ⭐ **NEW PRIMARY** → Similar to ARIES AC_PRODUCT (main production/forecast data)
- **phd_LSEPRODVAL** ⭐ **SECONDARY** → Secondary production data
- **phd_MONHIST** ⭐ **TERTIARY** → Monthly production history
- **phd_LSESEGMENT** ⭐ **SUPPORTING** → Production segments and time periods
- **phd_DAILY** → Daily production data

### Header Data
- **phd_VOLUME** → Reservoir and ultimate recovery data
- **phd_ZONE** → Completion and zone data
- **phd_GRAPHS** ⭐ **NEW** → Graph and visualization data

### Economic Data
- **phd_OWNER** → Ownership information
- **phd_INVEST** → CAPEX and investment data
- **phd_ECON** → Economic parameters (no data in this conversion)
- **phd_ROYALTY** → Royalty information (no data in this conversion)

### Supporting Data
- **phd_PRODUCTNAMES** → Product type definitions
- **phd_CLASS** → Reserve class definitions
- **phd_CATEGORY** → Well category definitions

## Key Improvements in Latest Conversion (pytopspeed-modernized 1.1.3)

The latest pytopspeed-modernized 1.1.3 conversion has successfully extracted comprehensive data with improved stability:

1. **phd_FORCAST**: 4,370 records ⭐ **PRIMARY PRODUCTION DATA**
2. **phd_LSEPRODVAL**: 1,330 records - Secondary production data
3. **phd_LSESEGMENT**: 475 records - Production segments
4. **phd_MONHIST**: 313 records - Monthly history
5. **phd_GRAPHS**: 95 records - Graph data
6. **phd_ECON**: 95 records ⭐ **NEW** - Economic data now populated
7. **phd_MAINLSE**: 95 records ⭐ **NEW** - Main lease data now populated
8. **mod_TEMPLATE**: 33 records - Template data
9. **mod_MODPRODVAL**: 170 records - Model production values
10. **mod_MODSEGMENT**: 1,752 records - Model segments

### Conversion Success Metrics:
- **Total Records**: 14,756 (increased from 14,564)
- **Conversion Time**: ~50 seconds
- **Files Processed**: 2 (TxWells.PHD, TxWells.mod)
- **Tables Created**: 76
- **Success Rate**: 100% - All tables successfully converted

## Summary

This final structure provides the most comprehensive view of the PhdWin database with:

- **Primary Production Data**: phd_FORCAST (4,370 records) - the main production/forecast table
- **Secondary Production Data**: phd_LSEPRODVAL (1,330 records) - additional production data
- **Supporting Production Data**: phd_MONHIST, phd_LSESEGMENT, phd_DAILY
- **Header Data**: phd_VOLUME, phd_ZONE, phd_GRAPHS
- **Economic Data**: phd_OWNER, phd_INVEST
- **Model Data**: Comprehensive modeling tables with templates and segments

The database now contains 14,564 total records across 76 tables, making it fully suitable for DCA integration with RESAID.