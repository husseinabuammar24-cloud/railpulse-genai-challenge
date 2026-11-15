"""Independently verify the Namur trip and route counts using local SQLite."""

import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote


DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "railpulse.db")).expanduser().resolve()
EXPECTED_COUNTS = {"total_trips": 859, "total_routes": 63}

NAMUR_COUNTS_SQL = """
SELECT
  COUNT(DISTINCT st.trip_id) AS total_trips,
  COUNT(DISTINCT r.route_id) AS total_routes
FROM stops s
JOIN stop_times st ON s.stop_id = st.stop_id
JOIN trips t ON st.trip_id = t.trip_id
JOIN routes r ON t.route_id = r.route_id
WHERE s.stop_name LIKE ?
  AND (s.location_type = 1 OR s.platform_code IS NULL);
"""


def main() -> int:
    if not DATABASE_PATH.is_file():
        print(f"Database not found: {DATABASE_PATH}", file=sys.stderr)
        print("Set DATABASE_PATH to the local GTFS SQLite database file.", file=sys.stderr)
        return 2

    # mode=ro prevents SQLite from creating a missing/empty database or changing data.
    database_uri = f"file:{quote(str(DATABASE_PATH))}?mode=ro"
    try:
        with sqlite3.connect(database_uri, uri=True) as connection:
            cursor = connection.execute(NAMUR_COUNTS_SQL, ("%Namur%",))
            result = cursor.fetchone()
    except sqlite3.Error as error:
        print(f"Could not read/query {DATABASE_PATH}: {error}", file=sys.stderr)
        return 2

    actual = dict(zip(("total_trips", "total_routes"), result))
    print(f"Database: {DATABASE_PATH}")
    print("Scope: distinct trip and route IDs at stop records matching '%Namur%'.")
    print("These are counts across the GTFS feed; the query does not calculate a per-day count.")
    print()

    matches_expected = True
    for name, value in actual.items():
        expected = EXPECTED_COUNTS[name]
        matches = value == expected
        matches_expected = matches_expected and matches
        status = "MATCH" if matches else "MISMATCH"
        print(f"{name}: actual={value}, screenshot_expected={expected} [{status}]")

    return 0 if matches_expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
