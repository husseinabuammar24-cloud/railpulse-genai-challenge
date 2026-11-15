import re
import sqlite3


ALLOWED_TABLES = frozenset({
    "agency", "routes", "trips", "stop_times", "stops",
    "transfers", "calendar", "calendar_dates", "translations", "feed_info",
})

FORBIDDEN_KEYWORDS = re.compile(
    r"\b(?:ATTACH|DETACH|ALTER|CREATE|DELETE|DROP|INSERT|REPLACE|REINDEX|"
    r"RELEASE|RENAME|REPLACE|REVOKE|SAVEPOINT|TRUNCATE|UPDATE|VACUUM|"
    r"GRANT|EXEC|EXECUTE)\b",
    flags=re.IGNORECASE,
)
BLOCKED_FUNCTIONS = frozenset({"load_extension", "readfile", "writefile"})


def _mask_literals_and_comments(sql: str) -> str:
    """Blank out strings, quoted identifiers, and comments for lexical checks."""
    chars = list(sql)
    index = 0
    length = len(sql)

    while index < length:
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < length else ""

        if char == "-" and next_char == "-":
            end = sql.find("\n", index + 2)
            end = length if end == -1 else end
            for position in range(index, end):
                if chars[position] != "\n":
                    chars[position] = " "
            index = end
            continue

        if char == "/" and next_char == "*":
            end = sql.find("*/", index + 2)
            end = length if end == -1 else end + 2
            for position in range(index, end):
                if chars[position] != "\n":
                    chars[position] = " "
            index = end
            continue

        if char in "'\"`[":
            closing = "]" if char == "[" else char
            chars[index] = " "
            index += 1
            while index < length:
                current = sql[index]
                chars[index] = " " if current != "\n" else "\n"
                if current == closing:
                    # SQL escapes quote delimiters by doubling them.
                    if index + 1 < length and sql[index + 1] == closing:
                        chars[index + 1] = " "
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue

        index += 1

    return "".join(chars)


def clean_sql_query(raw_llm_output: str) -> str:
    """Extract SQL from model formatting without silently truncating statements."""
    sql = (raw_llm_output or "").strip()
    code_block = re.search(r"```(?:sql)?\s*(.*?)```", sql, flags=re.IGNORECASE | re.DOTALL)
    if code_block:
        sql = code_block.group(1).strip()

    # Some models bold SQL functions; remove the formatting but preserve quoted SQL.
    sql = re.sub(r"\*\*(.*?)\*\*", r"\1", sql, flags=re.DOTALL)
    masked = _mask_literals_and_comments(sql)
    statement_start = re.search(r"\b(?:SELECT|WITH)\b", masked, flags=re.IGNORECASE)
    if statement_start:
        sql = sql[statement_start.start():].strip()
    return sql


def is_safe_query(sql_query: str) -> tuple[bool, str]:
    """Reject non-read queries; execution also enforces a SQLite authorizer."""
    if not isinstance(sql_query, str) or not sql_query.strip():
        return False, "Query is empty."

    masked = _mask_literals_and_comments(sql_query)
    if not re.match(r"\s*(?:SELECT|WITH)\b", masked, flags=re.IGNORECASE):
        return False, "Query must begin with SELECT or WITH."

    semicolons = [index for index, char in enumerate(masked) if char == ";"]
    if len(semicolons) > 1:
        return False, "Only one SQL statement is allowed."
    if semicolons and masked[semicolons[0] + 1:].strip():
        return False, "Only one SQL statement is allowed."

    forbidden = FORBIDDEN_KEYWORDS.search(masked)
    if forbidden:
        return False, f"Forbidden SQL operation: {forbidden.group(0).upper()}."

    return True, "Read-only query accepted; SQLite authorizer will enforce table access."


def install_readonly_authorizer(connection: sqlite3.Connection) -> None:
    """Restrict SQLite execution to reads from approved GTFS tables."""

    def authorize(action, argument1, argument2, database_name, _trigger_name):
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK

        if action == sqlite3.SQLITE_READ:
            table = (argument1 or "").lower()
            database = (database_name or "").lower()
            if database == "main" and table in ALLOWED_TABLES:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        if action == sqlite3.SQLITE_FUNCTION:
            function = (argument2 or argument1 or "").lower()
            if function in BLOCKED_FUNCTIONS:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        # Deny writes, schema changes, PRAGMA, ATTACH/DETACH, and other actions.
        return sqlite3.SQLITE_DENY

    connection.set_authorizer(authorize)
