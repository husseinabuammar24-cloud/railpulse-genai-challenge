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
    """Extracts raw SQL block from LLM markdown response."""
    sql = raw_llm_output.strip()
    if "```sql" in sql:
        sql = sql.split("```sql")[1].split("```")[0]
    elif "```" in sql:
        sql = sql.split("```")[1].split("```")[0]
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