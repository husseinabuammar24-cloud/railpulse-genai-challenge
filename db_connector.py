import os
import re
import sqlite3
import pandas as pd

# Path to your SQLite database file
DB_FILE = os.getenv("DATABASE_PATH", "railpulse.db")
FEED_METADATA_SQL = """SELECT feed_id, feed_publisher_name, feed_start_date, feed_end_date, feed_version
FROM feed_info
ORDER BY feed_id
LIMIT 1"""

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


def get_feed_metadata() -> tuple[pd.DataFrame, str]:
    """Return feed publisher/version/date metadata and its source SQL."""
    conn = get_connection()
    try:
        return pd.read_sql_query(FEED_METADATA_SQL, conn), FEED_METADATA_SQL
    except sqlite3.Error:
        return pd.DataFrame(), FEED_METADATA_SQL
    finally:
        conn.close()


def get_station_scope(sql_query: str) -> tuple[pd.DataFrame, str | None]:
    """Resolve stop-name LIKE filters into the exact matching stop records."""
    patterns = re.findall(
        r"(?:\b\w+\.)?\bstop_name\s+LIKE\s+'((?:''|[^'])*)'",
        sql_query,
        flags=re.IGNORECASE,
    )
    patterns = list(dict.fromkeys(pattern.replace("''", "'") for pattern in patterns))
    if not patterns:
        return pd.DataFrame(), None

    match_conditions = " OR ".join("stop_name LIKE ?" for _ in patterns)
    where_clause = f"({match_conditions})"
    uses_station_filter = (
        re.search(r"location_type\s*=\s*1", sql_query, flags=re.IGNORECASE)
        and re.search(r"platform_code\s+IS\s+NULL", sql_query, flags=re.IGNORECASE)
    )
    if uses_station_filter:
        where_clause += " AND (location_type = 1 OR platform_code IS NULL)"

    scope_sql = f"""SELECT stop_id, stop_name, location_type, parent_station, platform_code
FROM stops
WHERE {where_clause}
ORDER BY stop_name, stop_id"""

    conn = get_connection()
    try:
        scope = pd.read_sql_query(scope_sql, conn, params=patterns)
        return scope, scope_sql
    finally:
        conn.close()
