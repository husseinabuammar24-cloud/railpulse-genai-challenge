"""Allowlisted semantic query templates for common GTFS questions."""

from dataclasses import dataclass
import re


SEMANTIC_LAYER_VERSION = "gtfs_station_metrics_v1"


@dataclass(frozen=True)
class SemanticQuery:
    sql: str
    semantic_name: str
    version: str


def build_station_comparison_query(question: str) -> SemanticQuery | None:
    """Build a fixed station-comparison query for supported trip/route metrics.

    Station names are treated only as escaped SQL string values. Identifiers,
    tables, joins, and aggregate expressions come from this module's allowlist.
    Unsupported questions fall back to the app's guarded SQL-generation flow.
    """
    match = re.search(
        r"\bcompare\s+(.+?)\s+(?:and|versus|vs\.?|with)\s+(.+?)"
        r"(?=\s+by\b|[?.!]|$)",
        question,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    station_names = []
    for raw_name in match.groups():
        name = re.sub(r"\s+station$", "", raw_name.strip(), flags=re.IGNORECASE).strip(" '\"`")
        if not name or len(name) > 80 or not all(
            char.isalpha() or char in " -'’" for char in name
        ):
            return None
        station_names.append(name)

    if station_names[0].casefold() == station_names[1].casefold():
        return None

    question_lower = question.lower()
    selected_metrics = []
    if re.search(r"\b(trips?|trip ids?|scheduled service)\b", question_lower):
        selected_metrics.append(
            "COUNT(DISTINCT st.trip_id) AS distinct_trips"
        )
    if re.search(r"\b(routes?|route ids?)\b", question_lower):
        selected_metrics.append(
            "COUNT(DISTINCT t.route_id) AS distinct_routes"
        )
    if not selected_metrics:
        return None

    conditions = []
    for name in station_names:
        escaped = name.replace("'", "''")
        conditions.append(f"s.stop_name LIKE '%{escaped}%'")
    where_names = " OR ".join(conditions)
    select_metrics = ",\n       ".join(selected_metrics)
    sql = f"""SELECT s.stop_name AS station_name,
       {select_metrics}
FROM stops s
JOIN stop_times st ON s.stop_id = st.stop_id
JOIN trips t ON st.trip_id = t.trip_id
WHERE ({where_names})
  AND (s.location_type = 1 OR s.platform_code IS NULL)
GROUP BY s.stop_name
ORDER BY s.stop_name
LIMIT 20;"""
    return SemanticQuery(
        sql=sql,
        semantic_name="Station schedule comparison",
        version=SEMANTIC_LAYER_VERSION,
    )
