import re

# Block data-modifying SQL statements
FORBIDDEN_KEYWORDS = [
    r"\bDROP\b", r"\bDELETE\b", r"\bUPDATE\b", r"\bINSERT\b", 
    r"\bALTER\b", r"\bTRUNCATE\b", r"\bGRANT\b", r"\bREVOKE\b",
    r"\bEXEC\b", r"\bEXECUTE\b"
]

ALLOWED_TABLES = [
    "agency", "routes", "trips", "stop_times", "stops", 
    "transfers", "calendar", "calendar_dates", "translations", "feed_info"
]

def clean_sql_query(raw_llm_output: str) -> str:
    """Extract one SQL statement from model output and discard wrappers/comments."""
    sql = raw_llm_output.strip()
    code_block = re.search(r"```(?:sql)?\s*(.*?)```", sql, flags=re.IGNORECASE | re.DOTALL)
    if code_block:
        sql = code_block.group(1)

    # Remove markdown emphasis that some models add around SQL function names.
    sql = re.sub(r"\*\*(.*?)\*\*", r"\1", sql, flags=re.DOTALL)
    sql = sql.replace("`", "").strip()

    # Ignore model notes (including fact-ID comments) before the SQL statement.
    statement_start = re.search(r"\b(?:SELECT|WITH)\b", sql, flags=re.IGNORECASE)
    if not statement_start:
        return sql.strip()
    sql = sql[statement_start.start():]

    # Remove SQL comments, then keep only the first statement.
    sql = re.sub(r"(?m)^\s*--[^\n]*", "", sql)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    if ";" in sql:
        sql = sql.split(";", 1)[0] + ";"
    return sql.strip()

def is_safe_query(sql_query: str) -> tuple[bool, str]:
    """Validates SQL query against security policies."""
    clean_sql = sql_query.upper().strip()

    # Must start with SELECT or WITH (for CTEs)
    if not (clean_sql.startswith("SELECT") or clean_sql.startswith("WITH")):
        return False, "Query must strictly be a SELECT or WITH statement."

    # Check forbidden keywords
    for pattern in FORBIDDEN_KEYWORDS:
        if re.search(pattern, clean_sql):
            return False, f"Forbidden keyword detected matching pattern: {pattern}"

    # Basic check ensuring referenced tables match the GTFS schema
    found_table = False
    for table in ALLOWED_TABLES:
        if table.upper() in clean_sql:
            found_table = True
            break
    
    if not found_table:
        return False, "Query does not target valid GTFS database tables."

    return True, "Safe"
