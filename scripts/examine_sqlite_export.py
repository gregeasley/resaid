#!/usr/bin/env python3
"""Examine the SQLite export from the PhdWin parser"""

import sqlite3

def examine_sqlite_export():
    """Examine the SQLite database export"""
    db_path = "test_phdwin_export.db"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"Tables in database: {[t[0] for t in tables]}")
        
        # Examine table references
        print(f"\n=== Table References ===")
        cursor.execute("SELECT * FROM table_references")
        refs = cursor.fetchall()
        print(f"Found {len(refs)} table references:")
        for ref in refs:
            print(f"  ID: {ref[0]}, Type: {ref[1]}, Offset: 0x{ref[2]:06X}, Raw: {ref[3]}, Valid: {ref[4]}")
        
        # Examine database info
        print(f"\n=== Database Info ===")
        cursor.execute("SELECT * FROM database_info")
        info = cursor.fetchall()
        for item in info:
            print(f"  {item[0]}: {item[1]}")
        
        conn.close()
        
    except Exception as e:
        print(f"Error examining database: {e}")

if __name__ == "__main__":
    examine_sqlite_export()
