import os
import sqlite3
import pandas as pd

# Path to your SQLite database file
DB_FILE = os.getenv("DATABASE_PATH", "railpulse.db")

def get_connection():
    """Establishes connection to the SQLite database."""
    return sqlite3.connect(DB_FILE)

def execute_query(sql_query: str) -> pd.DataFrame:
    """Executes a validated SELECT query and returns results as a DataFrame."""
    conn = get_connection()
    try:
        df = pd.read_sql_query(sql_query, conn)
        return df
    finally:
        conn.close()