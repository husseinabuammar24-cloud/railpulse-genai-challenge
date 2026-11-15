# RailPulse GenAI Challenge

RailPulse AI is a Streamlit-based assistant for exploring Belgian railway schedule data with natural-language questions. It uses an LLM to draft SQLite queries over a GTFS database, displays the results, and produces a concise, traceable explanation. The project was built for the RailPulse GenAI learning challenge.

> **Data scope:** This project queries static GTFS schedule data. It does not provide live train positions, delays, passenger counts, or ridership data. Do not treat scheduled-trip counts as daily totals or measures of passenger demand.

## What it does

- Accepts questions about stations, stops, routes, trips, and schedules in a Streamlit chat interface.
- Uses either Groq-hosted inference or a locally running Ollama model to generate SQLite SQL and interpret results.
- Applies a basic SQL safety check before executing model-generated queries.
- Shows query results, generated SQL, relevant feed/station scope, and numeric fact IDs that link answer claims to returned values.
- Supports station comparisons with tables and charts when results have compatible station and count columns.
- Exports the chat and its analysis as a PDF.

## How it works

1. Ask a question in the Streamlit app.
2. The selected LLM generates a query using the GTFS schema and SQLite instructions in `prompts.py`.
3. `guardrails.py` cleans and checks the query; `db_connector.py` executes it against the configured SQLite database.
4. The app displays the returned data and prepares an explanation. Numeric claims are checked against values returned by the query.
5. Use **Download chat as PDF** to export the conversation.

The numeric fact IDs improve traceability, but they do not prove that the SQL itself is the right query or that the underlying feed is complete and current.

## Requirements

- Python 3.10 or later
- A SQLite database populated with the GTFS tables described below
- One LLM option:
  - **Groq:** a Groq API key
  - **Ollama:** Ollama installed and a model available locally (the app defaults to `llama3`)

The repository does not include `railpulse.db`. Supply your own compatible GTFS database. The connector uses the `DATABASE_PATH` environment variable when set; otherwise, it looks for `railpulse.db` in the current working directory.

## Setup

Clone the repository and install its dependencies:

```bash
git clone https://github.com/husseinabuammar24-cloud/railpulse-genai-challenge.git
cd railpulse-genai-challenge

python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
```

The app formats some data frames as Markdown tables. If that reports that `tabulate` is missing, install it with `pip install tabulate`.

### Configure the GTFS database

Set `DATABASE_PATH` to the location of your SQLite database before starting the app.

macOS / Linux:

```bash
export DATABASE_PATH="/path/to/your/gtfs.db"
```

Windows PowerShell:

```powershell
$env:DATABASE_PATH = "C:\path\to\your\gtfs.db"
```

If you leave it unset, place the database at `railpulse.db` in the repository directory. Check that the database is readable and contains the expected tables:

```bash
python check_tables.py
```

`check_tables.py` currently opens `railpulse.db` by that filename, so if your database has a different name, set `DATABASE_PATH` and use this quick check instead:

```bash
python -c "import os, sqlite3; c=sqlite3.connect(os.getenv('DATABASE_PATH', 'railpulse.db')); print(c.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\").fetchall()); c.close()"
```

### Choose an LLM provider

**Groq:** Start the app and enter your API key in the sidebar. Alternatively, set `GROQ_API_KEY` in the environment before launching. The app's current Groq model selection is `openai/gpt-oss-20b`.

macOS / Linux:

```bash
export GROQ_API_KEY="your-key"
```

Windows PowerShell:

```powershell
$env:GROQ_API_KEY = "your-key"
```

**Ollama:** Install and start Ollama, then download the default model if needed:

```bash
ollama pull llama3
```

The sidebar defaults to `http://localhost:11434` and model `llama3`; change these values there if your setup differs. Keep API keys out of source control.

### Run the app

```bash
streamlit run app.py --server.fileWatcherType=none
```

Open the local URL printed by Streamlit, usually `http://localhost:8501`.

## Example questions

These are examples of questions that fit the static GTFS data model:

- “What stations are in Namur?”
- “Which stops match Brussels, Brussel, or Bruxelles?”
- “How many distinct scheduled trips serve this station in the feed?”
- “Compare distinct scheduled trips and routes for these stations.”
- “Which routes have the most scheduled trips?”

Results depend on the GTFS feed you provide. A feed-level count is not automatically a count per day; service calendars must be considered for date-specific questions. The bundled prompts ask the model not to infer delays, passenger volumes, crowding, or capacity from schedule counts.

## Database schema

The prompts are written for the following standard GTFS tables and fields. Your database may have additional fields, but it should contain the tables needed for the questions you ask.

| Table | Example fields |
| --- | --- |
| `agency` | `agency_id`, `agency_name`, `agency_url`, `agency_timezone` |
| `routes` | `route_id`, `agency_id`, `route_short_name`, `route_long_name`, `route_type` |
| `trips` | `trip_id`, `route_id`, `service_id`, `trip_headsign`, `direction_id` |
| `stop_times` | `trip_id`, `stop_sequence`, `stop_id`, `arrival_time`, `departure_time` |
| `stops` | `stop_id`, `stop_name`, `stop_lat`, `stop_lon`, `location_type`, `parent_station`, `platform_code` |
| `transfers` | `from_stop_id`, `to_stop_id`, `transfer_type`, `min_transfer_time` |
| `calendar` | `service_id`, weekday flags, `start_date`, `end_date` |
| `calendar_dates` | `service_id`, `date`, `exception_type` |
| `translations` | `table_name`, `field_name`, `record_id`, `language`, `translation` |
| `feed_info` | `feed_publisher_name`, `feed_version`, `feed_start_date`, `feed_end_date` |

GTFS feeds can differ in optional columns and conventions. In particular, `stops` does not have an `agency_id` field in the schema used by this project. The app and its prompts are not a substitute for validating your own feed's schema.

## Repository layout

```text
.
├── app.py                  # Streamlit chat, query/analysis flow, charts, PDF export
├── db_connector.py         # SQLite connection, query execution, feed/station scope
├── guardrails.py           # SQL cleanup and basic safety checks
├── prompts.py              # GTFS-aware SQL and analysis prompts
├── check_tables.py         # Lists tables in railpulse.db
├── verify_namur_counts.py  # Optional check of known Namur feed-level counts
├── ERD.webp                # GTFS entity-relationship diagram
├── requirements.txt        # Python dependencies
└── README.md
```

`verify_namur_counts.py` also reads the database path from `DATABASE_PATH` (default: `railpulse.db`). It compares distinct trip and route counts for stop records matching `Namur` with the expected values embedded in that script. Treat those expected values as a dataset-specific check, not as a guarantee for other GTFS feeds.

## Safety and limitations

The app is a learning project, not a production-hardened database agent. `guardrails.py` permits queries beginning with `SELECT` or `WITH`, rejects several data-modification keywords, and checks for known GTFS table names. These are regex/string checks—not a SQL parser or a complete security boundary. Do not connect this app to a sensitive database or rely on the checks to protect untrusted data. Use a read-only database account/file and review generated SQL and results.

Other important limitations:

- Answers are bounded by the data and schema in the supplied GTFS database. Static GTFS does not contain real-time delay data unless your database has been separately extended.
- LLM-generated SQL and explanations can still be wrong. Review the displayed SQL and validate important results independently.
- Numeric fact IDs check whether displayed numeric claims correspond to query results; they do not validate the assumptions or scope of a query.
- Feed-level schedule counts should not be described as daily service without applying the relevant GTFS calendars and date exceptions.
- The app's station comparison view is available only for results with recognizable station and trip/route count columns.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| `no such table` or an empty result unexpectedly | Confirm `DATABASE_PATH` points to the intended GTFS database and that it contains the expected tables. |
| Groq API error | Check the key, account access, network connection, and the selected model availability. |
| Ollama connection/model error | Confirm Ollama is running, the configured URL is reachable, and the selected model has been pulled. |
| SQL safety check blocks a query | Inspect the generated SQL in the app. The basic checks may reject a query containing a blocked keyword even when it appears in another context. |
| `tabulate` import error | Run `pip install tabulate` in the active virtual environment. |
| Streamlit file-watcher noise | Launch with `--server.fileWatcherType=none` as shown above. |

## Development notes

The repository includes small utility scripts for inspecting the SQLite tables and checking a dataset-specific Namur count. There is no automated test suite currently documented in the repository. When changing query behavior, test the app against a disposable, representative GTFS database and review both generated SQL and output.

## License

No license file is currently included. Contact the repository owner before redistributing or reusing the project if you need explicit licensing terms.
