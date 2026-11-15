import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from xml.sax.saxutils import escape
from uuid import uuid4

import streamlit as st
import pandas as pd
from langchain_groq import ChatGroq
from langchain_community.llms import Ollama
from langchain_core.messages import HumanMessage, SystemMessage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from guardrails import is_safe_query, clean_sql_query
from db_connector import execute_query, get_feed_metadata, get_station_scope
from prompts import SYSTEM_PROMPT, CONSULTANT_PROMPT_TEMPLATE


def make_chat_pdf(messages):
    """Build a downloadable PDF transcript from the current chat session."""
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="RailPulse AI Chat Report",
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "ChatBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9, leading=13, spaceAfter=5, alignment=TA_LEFT,
    )
    heading_style = ParagraphStyle(
        "ChatHeading", parent=styles["Heading2"], textColor=colors.HexColor("#253858"),
        spaceBefore=10, spaceAfter=5,
    )
    story = [
        Paragraph("RailPulse AI Chat Report", styles["Title"]),
        Paragraph(datetime.now().strftime("Generated %d %B %Y at %H:%M"), styles["Italic"]),
        Spacer(1, 10),
    ]

    for message in messages:
        role = "You" if message["role"] == "user" else "RailPulse AI"
        story.append(Paragraph(escape(role), heading_style))
        content = message.get("report_content", message.get("content", ""))
        content = content.encode("cp1252", "replace").decode("cp1252")
        content = escape(content).replace("\n", "<br/>")
        story.append(Paragraph(content or " ", body_style))
        story.append(Spacer(1, 4))

    document.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def remove_pdf_export_request(question):
    """Keep export instructions out of the SQL-generation prompt."""
    cleaned = re.sub(
        r"\b(?:and\s+)?(?:then\s+)?(?:i\s+)?(?:need|want|would like)\s+"
        r"(?:(?:the|a)\s+)?(?:report|results?|output)\s+in\s+(?:a\s+)?pdf"
        r"(?:\s+format)?(?:\s+to\s+download)?[.!?]*",
        " ",
        question,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip(" ,.;:")


def is_pdf_only_request(question):
    if "pdf" not in question.lower():
        return False
    data_question_terms = r"\b(compare|show|find|list|how many|which|what|when|where|count|top|biggest|busiest|delay|route|station|stop|train|trip)\b"
    return re.search(data_question_terms, question, flags=re.IGNORECASE) is None


def _sql_result_expressions(sql_query):
    """Map output column aliases to the SELECT expressions that produced them."""
    match = re.search(r"\bSELECT\b(.*?)\bFROM\b", sql_query, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return {}

    select_list = match.group(1)
    expressions = []
    start = depth = 0
    quote = None
    for index, char in enumerate(select_list):
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            expressions.append(select_list[start:index].strip())
            start = index + 1
    expressions.append(select_list[start:].strip())

    result = {}
    for expression in expressions:
        alias_match = re.search(r"\s+AS\s+[\"'`]?([\w]+)[\"'`]?$", expression, flags=re.IGNORECASE)
        if alias_match:
            alias = alias_match.group(1)
            source_expression = expression[:alias_match.start()].strip()
        else:
            source_expression = expression
            alias = re.sub(r"[\"'`]", "", source_expression.rsplit(".", 1)[-1]).strip()
        result[alias.lower()] = source_expression
    return result


def build_numeric_facts(sql_query, result_frame):
    """Assign stable fact IDs to numeric cells returned by the executed query."""
    expressions = _sql_result_expressions(sql_query)
    facts = []
    for row_number, (_, row) in enumerate(result_frame.iterrows(), start=1):
        for column in result_frame.columns:
            value = row[column]
            if value is None:
                continue
            try:
                normalized = Decimal(str(value).replace(",", ""))
            except (InvalidOperation, ValueError):
                continue
            if not normalized.is_finite():
                continue
            expression = expressions.get(str(column).lower(), f"SQL output column {column}")
            facts.append({
                "id": f"F{len(facts) + 1}",
                "row": row_number,
                "column": str(column),
                "alias": str(column).lower(),
                "value": str(value),
                "normalized": normalized,
                "expression": expression,
                "result_row": {
                    str(row_column): row[row_column]
                    for row_column in result_frame.columns
                },
            })
    return facts


def format_fact_catalog(facts):
    return "\n".join(
        f"[{fact['id']}] result row {fact['row']}, column {fact['column']}, "
        f"value {fact['value']}; SQL expression: {fact['expression']}"
        for fact in facts
    ) or "No numeric result cells. Do not report numeric claims."


def annotate_result_frame(result_frame, facts):
    """Add the unique fact ID for each numeric result cell using its row/column address."""
    annotated = result_frame.astype(object).copy()
    column_positions = {str(column): index for index, column in enumerate(annotated.columns)}
    for fact in facts:
        column_index = column_positions.get(fact["column"])
        row_index = fact["row"] - 1
        if column_index is None or row_index >= len(annotated):
            continue

        value = fact["value"]
        try:
            number = Decimal(value.replace(",", ""))
            if number == number.to_integral_value() and not fact["column"].lower().endswith("_date"):
                value = f"{int(number):,}"
        except (InvalidOperation, ValueError):
            pass
        annotated.iat[row_index, column_index] = f"{value} [{fact['id']}]"
    return annotated


def station_comparison_view(result_frame, facts):
    """Return a compact station-by-metric table and chart data for paired counts."""
    metric_columns = {
        "trip": "Scheduled trips",
        "route": "Distinct routes",
    }
    metric_aliases = {
        "trip": (
            "distinct_trips", "distinct_scheduled_trips", "total_trips",
            "trip_count", "scheduled_trips",
        ),
        "route": ("distinct_routes", "total_routes", "route_count"),
    }
    fact_by_cell = {(fact["row"], fact["alias"]): fact for fact in facts}
    pattern = re.compile(r"^(.+?)_(trip|route)_count$", flags=re.IGNORECASE)
    stations = {}

    if result_frame.empty:
        return None

    normalized_columns = {str(column).lower(): column for column in result_frame.columns}
    station_column = next(
        (normalized_columns[name] for name in ("station", "station_name", "stop_name", "location")
         if name in normalized_columns),
        None,
    )

    # Support one result row per station (for example stop_name/distinct_trips/distinct_routes).
    if station_column:
        metric_result_columns = {
            metric: next(
                (normalized_columns[name] for name in aliases if name in normalized_columns),
                None,
            )
            for metric, aliases in metric_aliases.items()
        }
        for row_number, (_, result_row) in enumerate(result_frame.iterrows(), start=1):
            station_label = str(result_row[station_column])
            station_key = station_label.casefold()
            stations.setdefault(station_key, {"Station": station_label})
            for metric_key, column in metric_result_columns.items():
                if column is None:
                    continue
                try:
                    value = float(result_row[column])
                except (TypeError, ValueError):
                    continue
                fact = fact_by_cell.get((row_number, str(column).lower()))
                formatted_value = f"{value:,.0f}" if value.is_integer() else f"{value:,.2f}"
                if fact:
                    formatted_value += f" [{fact['id']}]"
                metric_label = metric_columns[metric_key]
                stations[station_key][metric_label] = formatted_value
                stations[station_key][f"_{metric_label}"] = value
    else:
        # Also support a single row with aliases such as namur_trip_count.
        result_row = result_frame.iloc[0]
        for column in result_frame.columns:
            match = pattern.fullmatch(str(column).lower())
            if not match:
                continue
            station_key, metric_key = match.groups()
            try:
                value = float(result_row[column])
            except (TypeError, ValueError):
                continue
            label = station_key.replace("_", " ").title()
            stations.setdefault(station_key, {"Station": label})
            fact = fact_by_cell.get((1, str(column).lower()))
            formatted_value = f"{value:,.0f}" if value.is_integer() else f"{value:,.2f}"
            if fact:
                formatted_value += f" [{fact['id']}]"
            metric_label = metric_columns[metric_key.lower()]
            stations[station_key][metric_label] = formatted_value
            stations[station_key][f"_{metric_label}"] = value

    if len(stations) < 2:
        return None

    ordered_metrics = [
        metric for metric in metric_columns.values()
        if any(metric in station for station in stations.values())
    ]
    if not ordered_metrics:
        return None

    display_rows = []
    chart_frame = []
    for station in stations.values():
        display_rows.append({
            "Station": station["Station"],
            **{metric: station.get(metric, "—") for metric in ordered_metrics},
        })
        chart_frame.append({
            "Station": station["Station"],
            **{metric: station.get(f"_{metric}") for metric in ordered_metrics},
        })
    return display_rows, chart_frame, ordered_metrics


def format_station_comparison_briefing():
    """Use validated query results for comparisons instead of model-generated numbers."""
    return (
        "**Comparison**\n\n"
        "The station counts are shown above with fact IDs linked to their source calculations. "
        "They describe scheduled identifiers in this GTFS feed, not daily passenger volumes.\n\n"
        "**Tactical recommendation**\n\n"
        "Use these counts to compare scheduled service coverage. Check ridership and operational "
        "performance data before making staffing or capacity decisions."
    )


def cite_numeric_claims(text, facts):
    """Attach validated fact IDs to answer numbers; mark values absent from results."""
    facts_by_value = {}
    for fact in facts:
        facts_by_value.setdefault(fact["normalized"], []).append(fact)

    def relevant_facts(candidates, context):
        columns = {fact["column"] for fact in candidates}
        if len(columns) == 1:
            return candidates

        words = set(re.findall(r"[a-z]+", context.lower()))
        scored = []
        for fact in candidates:
            terms = set(re.findall(r"[a-z]+", fact["alias"].replace("_", " ")))
            terms.update(re.findall(r"[a-z]+", fact["expression"].lower()))
            score = sum(
                1 for term in terms
                if term in words or any(word.startswith(term.rstrip("s")) for word in words)
            )
            scored.append((score, fact))
        best_score = max(score for score, _ in scored)
        if best_score == 0:
            return candidates
        return [fact for score, fact in scored if score == best_score]

    def fact_ids_for(number, context):
        candidates = facts_by_value.get(number)
        if not candidates:
            return None
        matches = relevant_facts(candidates, context)
        return ", ".join(f"[{fact['id']}]" for fact in matches)

    # List numbering is formatting, not a reported quantity.
    text = re.sub(r"(?m)^(\s*)\d+[.)]\s+", r"\1- ", text)

    # Discard model-written citations; regenerate IDs only from the result fact catalog.
    text = re.sub(r"\[Source:[^\]]*\]|\[F\d+\]", "", text)
    # Do not treat the numeric suffix of IDs such as gs:nmbssncb:8863008 as a metric.
    number_pattern = re.compile(
        r"(?<![\w.:/])(?:-?\d{1,3}(?:,\d{3})+|-?\d+(?:\.\d+)?)(?![\w.:/])"
    )
    unsupported = False

    def replace_number(match):
        nonlocal unsupported
        raw_number = match.group(0)
        try:
            number = Decimal(raw_number.replace(",", ""))
        except InvalidOperation:
            unsupported = True
            return "[unverified value omitted]"
        fact_ids = fact_ids_for(number, text[max(0, match.start() - 70):match.end() + 70])
        if not fact_ids:
            unsupported = True
            return "[unverified value omitted]"
        return f"{raw_number} {fact_ids}"

    text = number_pattern.sub(replace_number, text)

    number_words = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
        "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
        "nineteen": 19, "twenty": 20,
    }
    word_pattern = re.compile(r"\b(?:" + "|".join(number_words) + r")\b", re.IGNORECASE)

    def replace_number_word(match):
        nonlocal unsupported
        word = match.group(0)
        number = Decimal(number_words[word.lower()])
        fact_ids = fact_ids_for(number, text[max(0, match.start() - 70):match.end() + 70])
        if not fact_ids:
            unsupported = True
            return "[unverified value omitted]"
        return f"{number} {fact_ids}"

    text = word_pattern.sub(replace_number_word, text)
    def deduplicate_fact_ids(match):
        fact_ids = list(dict.fromkeys(re.findall(r"\[F\d+\]", match.group(0))))
        return " ".join(fact_ids)

    text = re.sub(r"\[F\d+\](?:\s*,?\s*\[F\d+\])*", deduplicate_fact_ids, text)
    return text, unsupported


def verify_fact_ids(text, facts):
    """Check each displayed numeric value against the IDs immediately following it."""
    facts_by_id = {fact["id"]: fact for fact in facts}
    number_pattern = re.compile(
        r"(?<![\w.:/])(?:-?\d{1,3}(?:,\d{3})+|-?\d+(?:\.\d+)?)(?![\w.:/])"
    )
    for match in number_pattern.finditer(text):
        try:
            number = Decimal(match.group(0).replace(",", ""))
        except InvalidOperation:
            return False
        following_text = text[match.end():match.end() + 100]
        cited_ids = re.findall(r"\[(F\d+)\]", following_text.split("\n", 1)[0])
        if not cited_ids:
            return False
        if any(fact_id not in facts_by_id or facts_by_id[fact_id]["normalized"] != number for fact_id in cited_ids):
            return False
    return True


def build_distinct_value_query(source_sql, fact):
    """Build a read-only distinct-value query scoped to the fact's grouped result row."""
    expression = fact["expression"]
    count_match = re.fullmatch(
        r"\s*COUNT\s*\(\s*DISTINCT\s+(.+?)\s*\)\s*",
        expression,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not count_match or re.match(r"\s*WITH\b", source_sql, flags=re.IGNORECASE):
        return None
    if len(re.findall(r"\bSELECT\b", source_sql, flags=re.IGNORECASE)) != 1:
        return None

    from_match = re.search(r"\bFROM\b", source_sql, flags=re.IGNORECASE)
    if not from_match:
        return None
    from_clause = source_sql[from_match.start():]

    # Keep FROM/JOIN/WHERE, trimming only top-level grouping, ordering, and limits.
    depth = 0
    quote = None
    clause_start = None
    group_expressions = []
    clause_pattern = re.compile(r"(?:GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT)\b", re.IGNORECASE)
    index = 0
    while index < len(from_clause):
        char = from_clause[index]
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            clause_match = clause_pattern.match(from_clause, index)
            if clause_match:
                clause_start = index
                if clause_match.group(0).upper().startswith("GROUP"):
                    # Pattern.match(..., index) returns absolute match positions.
                    group_start = clause_match.end()
                    group_end_match = re.search(
                        r"\b(?:HAVING|ORDER\s+BY|LIMIT)\b",
                        from_clause[group_start:],
                        flags=re.IGNORECASE,
                    )
                    group_end = (
                        group_start + group_end_match.start()
                        if group_end_match else len(from_clause)
                    )
                    group_text = from_clause[group_start:group_end]

                    # Split the GROUP BY list on top-level commas only.
                    item_start = nesting = 0
                    item_quote = None
                    for group_index, group_char in enumerate(group_text):
                        if item_quote:
                            if group_char == item_quote:
                                item_quote = None
                        elif group_char in "'\"`":
                            item_quote = group_char
                        elif group_char == "(":
                            nesting += 1
                        elif group_char == ")":
                            nesting = max(0, nesting - 1)
                        elif group_char == "," and nesting == 0:
                            group_expressions.append(group_text[item_start:group_index].strip())
                            item_start = group_index + 1
                    final_group = group_text[item_start:].strip()
                    if final_group:
                        group_expressions.append(final_group)
                break
        index += 1

    if clause_start is not None:
        from_clause = from_clause[:clause_start]
    from_clause = from_clause.strip().rstrip(";").rstrip()

    # A grouped result row (e.g. Namur) must drill down within that row's group.
    row_data = {
        str(alias).lower(): value for alias, value in fact.get("result_row", {}).items()
    }
    selected_expressions = _sql_result_expressions(source_sql)

    def normalize_sql(value):
        return re.sub(r"\s+", "", value).strip('`"[]').lower()

    normalized_groups = {normalize_sql(group) for group in group_expressions}
    row_filters = []
    for alias, selected_expression in selected_expressions.items():
        if alias not in row_data:
            continue
        if normalize_sql(alias) in normalized_groups or normalize_sql(selected_expression) in normalized_groups:
            group_expression = next(
                group for group in group_expressions
                if normalize_sql(group) in {
                    normalize_sql(alias), normalize_sql(selected_expression)
                }
            )
            value = row_data[alias]
            if value is None or pd.isna(value):
                row_filters.append(f"{group_expression} IS NULL")
            elif isinstance(value, (int, float, Decimal)):
                row_filters.append(f"{group_expression} = {value}")
            else:
                escaped_value = str(value).replace("'", "''")
                row_filters.append(f"{group_expression} = '{escaped_value}'")

    if row_filters:
        conjunction = " AND ".join(row_filters)
        if re.search(r"\bWHERE\b", from_clause, flags=re.IGNORECASE):
            from_clause += f"\nAND {conjunction}"
        else:
            from_clause += f"\nWHERE {conjunction}"
    return f"SELECT DISTINCT {count_match.group(1)} AS source_value\n{from_clause}\nORDER BY source_value;"


def render_distinct_value_drilldown(fact, source_sql, button_key):
    drilldown_sql = build_distinct_value_query(source_sql, fact)
    if not drilldown_sql:
        return

    st.markdown("**Distinct values counted by this calculation**")
    st.caption("Run this query to list the IDs included in this result row.")
    st.code(drilldown_sql, language="sql")
    result_key = f"{button_key}-values"
    if st.button("List counted values", key=button_key):
        safe, reason = is_safe_query(drilldown_sql)
        if safe:
            st.session_state[result_key] = execute_query(drilldown_sql)
        else:
            st.error(f"Drilldown blocked by SQL safety check: {reason}")

    if result_key in st.session_state:
        values_frame = st.session_state[result_key]
        st.success(
            f"Listed {len(values_frame):,} distinct IDs for {fact['id']} "
            f"(fact value: {fact['value']})."
        )
        st.dataframe(values_frame, use_container_width=True)


def render_fact_catalog_table(facts, source_sql, trace_id):
    """Render the fact catalog with a clickable value cell for every fact."""
    widths = [0.8, 1, 1.5, 1, 3]
    headers = st.columns(widths)
    for column, label in zip(headers, ("Fact ID", "Result row", "Column", "Value", "SQL expression")):
        column.markdown(f"**{label}**")

    for fact in facts:
        row = st.columns(widths)
        row[0].write(fact["id"])
        row[1].write(fact["row"])
        row[2].write(fact["column"])
        tooltip = (
            f"{fact['id']} · result row {fact['row']} · column {fact['column']} · "
            f"SQL: {fact['expression']}"
        )
        with row[3].popover(fact["value"], help=tooltip):
            st.markdown(f"**{fact['id']} — result row {fact['row']}, `{fact['column']}`**")
            st.write(f"Result value: `{fact['value']}`")
            st.markdown("**Calculation**")
            st.code(fact["expression"], language="sql")
            render_distinct_value_drilldown(
                fact, source_sql, f"catalog-drilldown-{trace_id}-{fact['id']}"
            )
            st.markdown("**Full source query**")
            st.code(source_sql, language="sql")
        row[4].markdown(f"`{fact['expression']}`")

# --- Page Config ---
st.set_page_config(
    page_title="RailPulse AI | Station Manager Co-Pilot",
    page_icon="🚉",
    layout="wide"
)

st.title("🚉 RailPulse AI: Operational Assistant")
st.caption("Intelligent GTFS Transit Analytics & Conversational Insights for SNCB/NMBS")

# --- Sidebar Configuration ---
with st.sidebar:
    st.header("⚙️ Provider Settings")
    provider = st.radio("LLM Backend", ["Groq (Cloud Free API)", "Ollama (Local)"])
    
    if provider == "Groq (Cloud Free API)":
        api_key = st.text_input("Groq API Key", type="password", value=os.getenv("GROQ_API_KEY", ""))
        model_name = st.selectbox("Model", ["openai/gpt-oss-20b"])
    else:
        ollama_url = st.text_input("Ollama URL", value="http://localhost:11434")
        model_name = st.text_input("Local Model", value="llama3")

# --- LLM Initialization ---
def get_llm():
    if provider == "Groq (Cloud Free API)":
        if not api_key:
            st.error("Please enter a valid Groq API Key.")
            st.stop()
        return ChatGroq(groq_api_key=api_key, model_name=model_name, temperature=0.0)
    else:
        return Ollama(base_url=ollama_url, model=model_name, temperature=0.0)

# --- Chat Interface ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# Render chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("facts") and message.get("source_sql"):
            history_trace_id = message.get("trace_id") or f"history-{id(message)}"
            catalog_trace_id = f"{history_trace_id}-catalog"
            if len(message["facts"]) <= 12:
                render_fact_catalog_table(
                    message["facts"], message["source_sql"], catalog_trace_id
                )
            else:
                with st.expander("Show Traceability Fact IDs"):
                    render_fact_catalog_table(
                        message["facts"], message["source_sql"], catalog_trace_id
                    )

# User Input
if user_prompt := st.chat_input("Ask about stations, schedules, routes, or delays..."):
    st.session_state.messages.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        if is_pdf_only_request(user_prompt):
            response_text = "Your chat transcript is ready to export. Use the Download chat as PDF button below."
            st.markdown(response_text)
            st.session_state.messages.append({"role": "assistant", "content": response_text})
        else:
            with st.spinner("Generating SQL query..."):
                try:
                    llm = get_llm()
                
                    # Ignore the export-format clause during SQL generation.
                    sql_question = remove_pdf_export_request(user_prompt) or user_prompt
                    messages = [
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(content=sql_question)
                    ]
                    raw_sql_response = llm.invoke(messages)
                    raw_sql = raw_sql_response.content if hasattr(raw_sql_response, 'content') else str(raw_sql_response)
                
                    sql_query = clean_sql_query(raw_sql)
                
                    st.markdown("**Generated Query:**")
                    st.code(sql_query, language="sql")

                    is_safe, reason = is_safe_query(sql_query)
                    if not is_safe:
                        warning = f"Security Interception: {reason}"
                        st.error(f"🛑 {warning}")
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": f"Generated SQL:\n{sql_query}\n\n{warning}"
                        })
                    else:
                        try:
                            df_results = execute_query(sql_query)
                        except Exception as sqlite_error:
                            repair_prompt = (
                                "Repair the failed query for SQLite. Preserve the user's requested analysis. "
                                "Use only SELECT/WITH SQL against the listed GTFS schema. "
                                "SQLite GROUP_CONCAT(DISTINCT expression) accepts one argument; "
                                "do not use STRING_AGG or PostgreSQL syntax. Return only the corrected SQL.\n\n"
                                f"User question: {sql_question}\n"
                                f"Failed SQL: {sql_query}\n"
                                f"SQLite error: {sqlite_error}"
                            )
                            repair_response = llm.invoke([
                                SystemMessage(content=SYSTEM_PROMPT),
                                HumanMessage(content=repair_prompt),
                            ])
                            repaired_sql = clean_sql_query(
                                repair_response.content if hasattr(repair_response, "content")
                                else str(repair_response)
                            )
                            repair_is_safe, repair_reason = is_safe_query(repaired_sql)
                            if not repair_is_safe:
                                raise ValueError(
                                    f"SQLite repair was blocked by the SQL safety check: {repair_reason}"
                                ) from sqlite_error

                            df_results = execute_query(repaired_sql)
                            sql_query = repaired_sql
                            st.info("The first query used unsupported SQL syntax. It was corrected for SQLite.")
                            st.markdown("**SQLite-corrected query:**")
                            st.code(sql_query, language="sql")

                        numeric_facts = build_numeric_facts(sql_query, df_results)
                        fact_catalog = format_fact_catalog(numeric_facts)
                        trace_id = uuid4().hex[:10]
                        feed_metadata, feed_metadata_sql = get_feed_metadata()
                        matched_stops, matched_stops_sql = get_station_scope(sql_query)
                        feed_metadata_text = (
                            feed_metadata.to_markdown(index=False)
                            if not feed_metadata.empty else "No feed_info metadata is available."
                        )
                        matched_stops_text = (
                            matched_stops.to_markdown(index=False)
                            if not matched_stops.empty else "No matching stop records were found."
                        )

                        comparison_view = None
                        if df_results.empty:
                            st.warning("No records returned for this query.")
                            response_text = "No records were found matching your query criteria."
                            result_text = response_text
                        else:
                            annotated_results = annotate_result_frame(df_results, numeric_facts)
                            comparison_view = station_comparison_view(df_results, numeric_facts)
                            if comparison_view:
                                comparison_rows, chart_rows, comparison_metrics = comparison_view
                                st.markdown("### Station comparison")
                                st.caption("Counts are from the executed SQL; fact IDs link each value to its source calculation.")
                                st.dataframe(comparison_rows, hide_index=True, use_container_width=True)
                                chart_columns = st.columns(len(comparison_metrics))
                                for index, metric in enumerate(comparison_metrics):
                                    with chart_columns[index]:
                                        st.caption(metric)
                                        chart_data = pd.DataFrame([
                                            {"Station": row["Station"], metric: row[metric]}
                                            for row in chart_rows
                                            if row.get(metric) is not None
                                        ])
                                        st.bar_chart(chart_data, x="Station", y=metric)
                                with st.expander("Raw SQL result row"):
                                    st.dataframe(annotated_results, use_container_width=True)
                            else:
                                st.markdown("**Query Results:**")
                                st.dataframe(annotated_results, use_container_width=True)
                            result_text = df_results.to_markdown(index=False)

                            st.markdown("**GTFS feed coverage:**")
                            if feed_metadata.empty:
                                st.caption("The database does not provide feed_info metadata.")
                            else:
                                st.dataframe(feed_metadata, use_container_width=True)
                            with st.expander("Feed metadata source SQL"):
                                st.code(feed_metadata_sql, language="sql")

                            if matched_stops_sql:
                                st.markdown("**Matched stop records (station scope):**")
                                if matched_stops.empty:
                                    st.caption("No stop records matched the query's stop-name filters.")
                                else:
                                    st.dataframe(matched_stops, use_container_width=True)
                                with st.expander("Matched stop scope source SQL"):
                                    st.code(matched_stops_sql, language="sql")

                            if numeric_facts:
                                st.markdown("### Traceability Fact IDs")
                                if len(numeric_facts) <= 12:
                                    render_fact_catalog_table(
                                        numeric_facts, sql_query, f"{trace_id}-catalog"
                                    )
                                else:
                                    with st.expander("Show Traceability Fact IDs"):
                                        render_fact_catalog_table(
                                            numeric_facts, sql_query, f"{trace_id}-catalog"
                                        )

                            if comparison_view:
                                advice_text = format_station_comparison_briefing()
                                has_unverified_values = False
                            else:
                                consultant_prompt = CONSULTANT_PROMPT_TEMPLATE.format(
                                    user_query=sql_question,
                                    sql_query=sql_query,
                                    query_data=df_results.to_markdown(index=False),
                                    fact_catalog=fact_catalog,
                                )
                                raw_advice = llm.invoke([HumanMessage(content=consultant_prompt)])
                                advice_text = (
                                    raw_advice.content if hasattr(raw_advice, "content")
                                    else str(raw_advice)
                                )
                                advice_text, has_unverified_values = cite_numeric_claims(
                                    advice_text, numeric_facts
                                )
                            fact_ids_valid = verify_fact_ids(advice_text, numeric_facts)
                            if has_unverified_values or not fact_ids_valid:
                                traceability_status = (
                                    "REVIEW REQUIRED: at least one numeric claim was unverified "
                                    "or did not match its fact ID."
                                )
                                st.warning(
                                    "Fact ID check needs review. Unmatched numbers are marked unverified; "
                                    "compare the remaining IDs with the fact catalog."
                                )
                            else:
                                traceability_status = (
                                    "PASS: each displayed numeric value matches the result value for its cited fact ID."
                                )
                                st.success("Fact ID check passed: citations match the query result values.")
                        
                            st.markdown("---")
                            st.markdown("### 💡 RailPulse Tactical Briefing")
                            st.markdown(advice_text)
                        
                            response_text = advice_text

                        report_content = (
                            f"Source SQL (reproducible query):\n{sql_query}\n\n"
                            f"Query Result Rows (source data):\n{result_text}\n\n"
                            f"GTFS Feed Metadata Source SQL:\n{feed_metadata_sql}\n"
                            f"GTFS Feed Metadata Rows:\n{feed_metadata_text}\n\n"
                            f"Matched Stop Scope SQL:\n{matched_stops_sql or 'Not available: no stop-name LIKE filters found.'}\n"
                            f"Matched Stop Scope Rows:\n{matched_stops_text}\n\n"
                            f"Traceability Fact Catalog:\n{fact_catalog}\n\n"
                            f"Fact ID Validation:\n{traceability_status if not df_results.empty else 'No result rows to validate.'}\n\n"
                            f"Analysis with verified fact IDs:\n{response_text}"
                        )
                        assistant_message = {
                            "role": "assistant",
                            "content": response_text,
                            "report_content": report_content,
                        }
                        if not df_results.empty:
                            assistant_message.update({
                                "fact_answer": response_text,
                                "facts": numeric_facts,
                                "source_sql": sql_query,
                                "trace_id": trace_id,
                            })
                        st.session_state.messages.append(assistant_message)

                except Exception as e:
                    st.error(f"An error occurred: {str(e)}")
                    st.session_state.messages.append({"role": "assistant", "content": f"Error: {e}"})

if st.session_state.messages:
    st.download_button(
        "📄 Download chat as PDF",
        data=make_chat_pdf(st.session_state.messages),
        file_name="railpulse-chat-report.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
