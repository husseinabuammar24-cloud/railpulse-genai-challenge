# 🚉 RailPulse AI: Intelligent Transit Insights

**Repository:** railpulse-genai-challenge
**Type of Challenge:** Learning
**Duration:** 5 days
**Team:** Solo

An open-source, zero-cost AI operational assistant connecting GTFS data infrastructure to natural language recommendations for SNCB/NMBS station managers.

---

## 📖 The Mission

RailPulse is an urban mobility consulting firm. The Belgian National Railway company (SNCB/NMBS) has modernized its infrastructure: data flows from the iRail API through a serverless cloud pipeline into Azure SQL, with executives tracking live trends on a Power BI dashboard.

This project builds an intelligent, completely free-to-run AI assistant that connects to that data infrastructure and translates complex transit data into natural language recommendations for station managers — without incurring third-party API costs.

### Mission Objectives
- **Local & Free LLM Integration** — Ollama (Llama 3) locally, or Groq's free-tier inference API.
- **Text-to-SQL / Contextual Routing** — Prompts that let small open-source models translate natural language into accurate SQL without hallucinating.
- **Agentic Guardrails** — Strict programmatic and prompt-based filters that block unauthorized or destructive database operations.

---

## 🏗️ Architecture Overview

```
┌─────────────────┐       ┌──────────────────────┐       ┌─────────────────────────┐
│ Streamlit UI    │ ──1──>│ Python Core (Agent)  │ ──2──>│ LLM (Ollama / Groq)     │
│ (User Query)    │       │                       │ <──3──│ (Generates SQL & Recs)  │
└─────────────────┘       └──────────┬────────────┘       └─────────────────────────┘
                                      │
                              4. Safety Guardrail
                              (Regex / Keyword Check)
                                      │
                                      ▼
                           ┌─────────────────────┐
                           │ SQLite / Azure SQL  │
                           │ (GTFS Schema)       │
                           └─────────────────────┘
```

---

## 📂 Project Structure

```
railpulse-genai-challenge/
├── app.py                # Streamlit interactive chat portal
├── check_tables.py       # Utility script to list tables in the DB
├── db_connector.py       # SQLite/pyodbc database connector
├── ERD.webp               # Entity-Relationship Diagram of the GTFS schema
├── guardrails.py          # SQL injection & safety regex layer
├── prompts.py              # System prompts, GTFS schema, few-shot examples
├── railpulse.db             # SQLite database (real GTFS data)
├── railway_gtfs.db          # Legacy/empty DB file — safe to delete once
│                              db_connector.py points at railpulse.db
├── requirements.txt         # Project dependencies
└── README.md                 # This file
```

> 🧹 **Cleanup tip:** `railway_gtfs.db` was auto-created early on when
> `db_connector.py` pointed at the wrong filename. It's empty and can be
> deleted once you've confirmed `DB_FILE` in `db_connector.py` points to
> `railpulse.db` (verify with `python3 check_tables.py`).

---

## 🧬 GTFS Database Schema

| Table | Key Columns |
|---|---|
| `agency` | agency_id (PK), agency_name, agency_url, agency_timezone |
| `routes` | route_id (PK), agency_id (FK), route_short_name, route_long_name, route_type |
| `trips` | trip_id (PK), route_id (FK), service_id (FK), trip_headsign, direction_id |
| `stop_times` | trip_id (PK/FK), stop_sequence (PK), stop_id (FK), arrival_time, departure_time |
| `stops` | stop_id (PK), stop_code, stop_name, stop_lat, stop_lon, location_type, parent_station, platform_code |
| `transfers` | from_stop_id (PK/FK), to_stop_id (PK/FK), transfer_type, min_transfer_time |
| `calendar` | service_id (PK), monday…sunday, start_date, end_date |
| `calendar_dates` | service_id (PK/FK), date (PK), exception_type |
| `translations` | table_name (PK), field_name (PK), record_id, language (PK), translation |
| `feed_info` | feed_id (PK), feed_publisher_name, feed_version, feed_start_date, feed_end_date |

> ⚠️ **Note:** `stops` has **no** `agency_id` column — never JOIN `stops` directly to `agency`.
>
> ⚠️ **Note:** No table above contains a delay column (e.g. `delay_seconds`, `actual_arrival`, or any real-time field). See [Known Limitations](#-known-limitations) — this directly affects the "worst average delay" example query and the weekly report generator.

---

## 🚀 Quickstart Guide

### Prerequisites
* Python 3.10 or higher
* [Ollama](https://ollama.ai/) (for local execution) or a [Groq API Key](https://console.groq.com/) (free tier)

---

### Step 1: Install Dependencies

```bash
git clone https://github.com/your-username/railpulse-genai-challenge.git
cd railpulse-genai-challenge

python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

pip install -r requirements.txt
```

`requirements.txt` should include:
```
streamlit>=1.30.0
langchain-core>=0.1.0
langchain-groq>=0.1.0
langchain-community>=0.0.20
pandas>=2.0.0
python-dotenv>=1.0.0
tabulate>=0.9.0
```

### Step 2: Set Up an LLM Backend

**Option A — Ollama (local, free):**
```bash
ollama run llama3
```

**Option B — Groq (free cloud tier):**
Get a free key at [console.groq.com](https://console.groq.com/) → API Keys → Create API Key, then paste it into the sidebar's "Groq API Key" field when the app is running.

### Step 3: Verify Your Database
Check what tables actually exist in your `.db` file before running the app:
```bash
python check_tables.py
```
Expected output:
```
Tables found in railpulse.db: [('agency',), ('routes',), ('calendar',), ('calendar_dates',),
('trips',), ('stops',), ('stop_times',), ('transfers',), ('feed_info',), ('translations',)]
```
Make sure `db_connector.py` points at the **correct** database filename (e.g. `railpulse.db`, not an empty auto-created `railway_gtfs.db`).

### Step 4: Run the Application
```bash
streamlit run app.py --server.fileWatcherType=none
```
The `--server.fileWatcherType=none` flag prevents Streamlit's file watcher from scanning unrelated ML libraries (e.g. `transformers`/`torchvision`), which otherwise fills the terminal with harmless `ModuleNotFoundError: No module named 'torchvision'` noise.

Open the app at the URL shown in your terminal (e.g. `http://localhost:8501`).

---

## 💬 Example Queries

- "What are the stations in Namur?"
- "What are the stations in Brussels?"
- "Which platform at Brussels-Central had the worst average delay this morning?" *(requires delay data — see [Known Limitations](#-known-limitations))*
- "List the top 5 routes with the most trips."

---

## 🛡️ Security & Guardrails

`guardrails.py` intercepts every LLM-generated query before execution:

```python
import re

FORBIDDEN_KEYWORDS = [
    r"\bDROP\b", r"\bDELETE\b", r"\bUPDATE\b", r"\bINSERT\b",
    r"\bALTER\b", r"\bTRUNCATE\b", r"\bEXEC\b", r"\bGRANT\b"
]

def validate_sql_query(query: str) -> tuple[bool, str]:
    """Validates generated SQL to ensure read-only execution."""
    cleaned_query = query.strip()

    if not re.match(r"^(SELECT|WITH)\b", cleaned_query, re.IGNORECASE):
        return False, "Query blocked: Only read-only SELECT queries are allowed."

    if ";" in cleaned_query.rstrip(";"):
        return False, "Query blocked: Multi-statement execution (semicolons) is disabled."

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(keyword, cleaned_query, re.IGNORECASE):
            return False, f"Query blocked: Dangerous keyword detected."

    return True, "Valid Query"
```

**Rules enforced:**
- Only `SELECT` / `WITH` (CTE) statements are allowed.
- No `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `EXEC`, or `GRANT`.
- No multi-statement chaining via semicolons.

> ⚠️ See [Known Limitations](#-known-limitations) — the function name here (`validate_sql_query`) does not match what `app.py` imports, and keyword/statement filtering alone doesn't verify which tables a query actually touches.

---

## 🧠 Prompt Engineering Highlights (`prompts.py`)

Key lessons learned while tuning `SYSTEM_PROMPT` for a small local model (Llama 3 8B):

1. **Multi-lingual station names matter.** Belgian GTFS stores central-city stations in French/Dutch (`Bruxelles-Midi`, `Bruxelles-Nord`, `Bruxelles-Central`) rather than English (`Brussels`). Always match all variants:
   ```sql
   WHERE (stop_name LIKE '%Brussel%' OR stop_name LIKE '%Bruxelles%' OR stop_name LIKE '%Brussels%')
   ```
2. **Deduplicate platforms.** Each platform is its own row in `stops`. Use `SELECT DISTINCT stop_name` plus a parent-station filter so a single multi-platform hub doesn't consume the whole `LIMIT`:
   ```sql
   AND (location_type = 1 OR platform_code IS NULL)
   ```
3. **Never join `stops` to `agency`** — there is no `agency_id` column on `stops`.
4. **Metric conversion.** Delay values are stored in seconds; the consultant response template explicitly converts them to minutes for readability.
5. **Few-shot examples are essential** for smaller open-source models — without a matching example, the model tends to fall back to a generic, less accurate query pattern.

---

## 📊 Nice-to-Have: Automated Weekly Executive Brief

`generate_report.py` extracts the top 5 delay anomalies and writes a Markdown executive summary:

```bash
python3 generate_report.py
```

Produces `WEEKLY_EXECUTIVE_BRIEF.md` containing:
- A table of the top 5 network delay anomalies (converted to minutes)
- Consultant-style operational recommendations (platform re-allocation, dwell-time optimization, etc.)

> ⚠️ Depends on delay data existing in `railpulse.db` — see [Known Limitations](#-known-limitations).

---

## ⚠️ Known Limitations

These are open risks that have **not been independently verified** against the running code and database. They're listed here deliberately, ahead of submission, so reviewers (and future-me) know exactly what "done" does and doesn't mean yet.

- **Delay-data coverage is unconfirmed.** The schema documented above is static GTFS only — no `delay_seconds`, `actual_arrival`, or other real-time/delay column appears in any listed table. The example query *"Which platform had the worst average delay this morning?"*, the delay-to-minutes conversion described under Prompt Engineering, and `generate_report.py`'s "top 5 delay anomalies" all assume this data exists somewhere. It has not been confirmed that it does. Verify with:
  ```bash
  sqlite3 railpulse.db ".schema stop_times"
  ```
  If no delay-related column turns up anywhere in the DB, these features will either fail outright or the LLM will hallucinate a plausible-sounding column name.

- **Guardrail function name mismatch (possible import error).** `app.py` imports `is_safe_query` from `guardrails.py`; the function shown in this README is named `validate_sql_query`. Whichever name is actually defined in the live file, the other reference is stale and one of the two will break on import. Confirm with:
  ```bash
  grep -n "^def " guardrails.py
  ```

- **Guardrail is keyword/regex-based, not AST-based.** It checks for forbidden keywords and a leading `SELECT`/`WITH`, but does not parse the query to verify which tables are actually referenced in `FROM`/`JOIN`. A query can pass validation while still reading unintended tables (e.g. schema metadata) via a comment or subquery trick. Treat this as a partial mitigation, not a hard security boundary, until it's replaced with real SQL parsing (e.g. `sqlglot`).

- **No enforced row limit in code.** `LIMIT` is requested via prompt instruction only (e.g. "add LIMIT 20"); nothing in `guardrails.py` or `db_connector.py` enforces a cap if the model omits it.

- **Few-shot examples are static, not dynamic.** The brief asks for "dynamic" few-shot prompting (examples selected/rotated based on the incoming question); the current implementation always injects the same fixed examples regardless of query.

- **Unit conversion (seconds → minutes) is prompt-enforced, not code-enforced.** Correctness depends on the LLM doing the arithmetic correctly rather than a deterministic transform (e.g. `df['delay_min'] = df['delay_sec'] / 60`) applied in pandas before the value ever reaches the model.

- **Raw exception messages may leak internal details.** Errors from `execute_query` (e.g. a malformed query slipping past the guardrail) are currently surfaced to the user as the raw exception string, which can expose schema or file-path information.

---

## 🩹 Troubleshooting Notes

| Symptom | Cause | Fix |
|---|---|---|
| `SyntaxError: invalid syntax` in `prompts.py` | Mismatched or extra `"""` triple-quote characters | Ensure every multi-line string starts and ends with exactly **three** double quotes |
| `no such table: stops` | `db_connector.py` points to an empty auto-created `.db` file | Confirm the correct filename via `python3 check_tables.py` and update `DB_FILE` |
| `ImportError: cannot import name 'CONSULTANT_PROMPT_TEMPLATE'` | Variable missing or `prompts.py` not saved | Ensure the file is saved (no unsaved-changes dot on the VS Code tab) and both variables are defined |
| `ImportError: cannot import name 'is_safe_query'` | `guardrails.py` actually defines `validate_sql_query` (or vice versa) | Align the function name in `guardrails.py` with what `app.py` imports — see Known Limitations |
| Query returns only one Brussels station | Search only matched `%Brussels%`, missing French/Dutch names, plus duplicate platform rows | Add multi-language `OR` clauses and `SELECT DISTINCT` + parent-station filter (see Prompt Engineering above) |
| `Security Alert: Query blocked` | Model generated a non-`SELECT` query, or stale conversation context confused a small local model | Clear chat / restart Streamlit; consider testing with Groq's larger hosted model to confirm the prompt itself is correct |
| Terminal flooded with `ModuleNotFoundError: No module named 'torchvision'` | Streamlit's file watcher inspects unrelated `transformers` vision submodules | Run with `--server.fileWatcherType=none`, or `pip install torchvision` |
| `Import tabulate failed` | Missing `tabulate` package used for Markdown table formatting | `pip3 install tabulate` |
| Changes to `prompts.py` don't take effect | Streamlit caches imported Python modules in memory | Clear cache (menu → *Clear cache*) and/or restart the server: `Ctrl+C` then `streamlit run app.py` |
| `python: command not found` on macOS | macOS uses `python3` by default | Use `python3 script.py` instead of `python script.py` |
| "Worst average delay" query fails or returns a hallucinated column | No delay column exists in the current schema | See Known Limitations — confirm with `sqlite3 railpulse.db ".schema stop_times"` |

---

## ✅ Pre-Submission Checklist

- [x] Local & free LLM integration (Ollama `llama3` or Groq free tier)
- [x] Deterministic Text-to-SQL translation with schema-aware prompting
- [ ] Metric conversion (seconds → minutes) — *prompt-enforced only, not code-enforced; see Known Limitations*
- [x] Interactive Streamlit chat portal
- [ ] SQL guardrails blocking `DROP` / `DELETE` / `UPDATE` / `INSERT` — *present, but keyword/regex-based rather than AST-based, and function naming needs to be reconciled with `app.py`; see Known Limitations*
- [ ] Few-shot prompting tuned for an 8B parameter open-source model — *static examples only, not dynamic as specified in the brief*
- [ ] Automated weekly executive brief generator — *implemented, but contingent on delay data that hasn't been confirmed to exist*
- [ ] Verified end-to-end against real GTFS data in `railpulse.db` — *not yet confirmed; the schema shown has no delay column, and the core example query depends on one*

---

## 🔧 Recommendations Before Submission

Given limited time remaining, in priority order:

1. **Resolve the delay-data question first — it blocks the core must-have.** Run `sqlite3 railpulse.db ".schema stop_times"` (and check `trips`/other tables) to see if a delay column exists anywhere under a different name. If it does, update the schema table above to document it. If it genuinely doesn't exist, either (a) derive a quick proxy delay metric from what's available, or (b) scope the example query and checklist claim down to something the schema actually supports — a smaller working demo beats a demo that fails live on its own example question.
2. **Fix the guardrail function name mismatch.** Confirm which name (`is_safe_query` or `validate_sql_query`) is actually defined in `guardrails.py` and make sure it matches what `app.py` imports, or the app won't start.
3. **If time allows, harden the guardrail** to check actual `FROM`/`JOIN` targets rather than keyword/substring matching, and add a hard `LIMIT` fallback in code (e.g. truncate the result DataFrame regardless of what SQL ran).
4. **Move unit conversion into code.** Compute `delay_min` in pandas rather than relying on the LLM to convert seconds to minutes correctly — small, deterministic, removes a source of hallucinated arithmetic.
5. **Lowest priority: dynamic few-shot selection.** Nice differentiator per the brief's wording, but not worth spending remaining time on relative to the items above.
6. **Before final submission, run the exact example queries listed in this README** end-to-end and confirm the outputs, rather than relying on the checklist as a proxy for "it works."

---

## 📜 License

Open-source project built for the RailPulse GenAI Learning Challenge.