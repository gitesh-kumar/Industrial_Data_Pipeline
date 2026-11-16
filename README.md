# Industrial Agentic AI System
### Factory monitoring with a LangChain SQL agent, an MCP server and full tracing

---

## What This Project Does

This system monitors factory machinery and translates raw sensor data into financial risk. It tells you not just that a machine is running hot but exactly how much that is costing you per hour, and whether you should shut it down. You can then ask questions about the factory in plain English and get answers that come from the data.

I built this because I spent 4 years at Hindustan Petroleum Corporation working with SCADA systems and watching engineers make critical decisions based on Excel sheets pulled manually from plant historians. This project automates that workflow.

All machine data is simulated. There is no real plant behind it.

---

## Architecture

The pipeline follows the **Medallion Architecture** used by companies like Databricks and Microsoft for production data lakes.

**Bronze Layer** - Raw ingestion. Seventeen factory machines (turbines, pumps, compressors, motors, generators, heat exchangers) generate sensor telemetry every 3 seconds. Vibration, temperature, and power consumption are captured and appended to a time-series store. Anomaly spikes are injected probabilistically to simulate real failure events.

**Silver Layer** - Cleaning and validation. Raw data is deduplicated, quality-flagged (PASS, HIGH_TEMP_WARN, VIBRATION_CRITICAL, FAILURE_SPIKE, DEGRADATION_WARN), unit-converted, and enriched with a composite risk score before being loaded into a structured SQL table.

**Gold Layer** - Business intelligence. Simulated German peak and off-peak electricity prices are applied to each machine's power consumption to calculate hourly energy cost in euros. Machines are classified by efficiency status against limits for their own machine type and given operational recommendations (CONTINUE, REDUCE_LOAD, SCHEDULE_MAINTENANCE, IMMEDIATE_SHUTDOWN).

**Governance Layer** - Automated pipeline health scoring. Every run calculates a data quality percentage and flags degradation in sensor reliability.

---

## The AI Layer

One LangChain agent with one tool. The tool is `run_sql`. The model reads a description of the database, writes the SQL itself, runs it through the tool and answers from the rows it gets back.

The model is never trusted to be safe. `sql_guard.py` sits between the model and the database and checks every query in four layers:

1. The database is opened read-only.
2. A SQLite authorizer allows only reads on the tables listed in the data dictionary.
3. Only a single SELECT statement is accepted.
4. A 3 second timeout and a limit of 50 rows apply.

If a query is rejected, the agent gets the error back and can try again. It has at most five queries per question.

**Reasoning beyond the data.** Many real questions have no column that answers them directly. The agent is built to handle four cases. A question that has nothing to do with the factory gets a plain answer without any query. A question the data answers directly gets one query. A question with no exact column ("which machine is wasting the most energy?") makes the agent say what is not measured, pick the connected measurements, query them, and label the answer as an inference. A question that needs facts from outside the data is answered with that limit stated. The prompt describes this method. It does not contain example questions.

**Two modes**, set with `AI_MODE`:

- **Cloud (default)** - Groq, model set by `GROQ_MODEL`. If Groq is down after a query has already run, the system returns the raw rows with a notice instead of failing.
- **Local** - Ollama, model set by `OLLAMA_MODEL`. Runs on your machine and sends no data and no traces to the cloud. This is for environments where operational data cannot leave the site. Answer quality depends on the model. A small 8B model reasons less well than the cloud model. The model must support tool calling (llama3.1 or qwen2.5, not plain llama3).

**Tracing.** In cloud mode every run is traced to Langfuse and LangSmith: the prompt, each tool call, the SQL, the rows and the answer. Tracing turns on when the keys are set. It is always off in local mode.

**Evaluation.** `eval_assistant.py` and `eval_questions.py` hold 39 test questions in these groups: direct answers, inference questions, refusals, safety attacks and unknown answers. Each answer is graded by rules, including whether every number in the answer appears in the query results. The grader is tested with a scripted good model and a scripted bad model so that it can be trusted before it judges a real one. It cannot catch shallow reasoning when the numbers are correct.

---

## MCP Server

The same data is also available as a [Model Context Protocol](https://modelcontextprotocol.io) server, so any MCP client (Claude Desktop, Cursor, another agent) can use it without any change to the project.

**Live demo page:** https://industrialdatapipeline-mcp.up.railway.app/

The page has four buttons that send real MCP requests from your browser to the server and show the request and the response: list the tools, describe the database, run a query, and try a DELETE that the guard rejects.

**MCP endpoint:** `https://industrialdatapipeline-mcp.up.railway.app/mcp` (Streamable HTTP)

| Tool | What it does |
|---|---|
| `describe_database` | Returns the tables, columns, allowed values and rules |
| `run_sql` | Runs one read-only SELECT through `sql_guard` |
| `ask_factory` | Runs the whole assistant. Off on the public server, because it uses model quota. Switch it on with `MCP_ASK=1`. It has a length limit, a 10 minute cache and 10 calls per minute. |

All tools are marked read-only and go through the same guard as the agent.

**Run it locally (stdio):**
```bash
python mcp_server.py
```
For Claude Desktop add this to `claude_desktop_config.json` with your own absolute paths:
```json
{
  "mcpServers": {
    "industrial-factory": {
      "command": "C:\\path\\to\\venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\mcp_server.py"]
    }
  }
}
```

**Run it as a web service:** set `MCP_TRANSPORT=http`. The server then listens on `PORT` and runs without sessions.

---

## REST API

The pipeline is wrapped in a FastAPI service with the following endpoints:

| Endpoint | Description |
|---|---|
| `GET /dashboard` | Industrial command center UI |
| `GET /machines` | Current status of all 17 machines |
| `GET /machines/{id}/risk` | Risk profile for a specific machine |
| `GET /pipeline/health` | Data quality score and flag breakdown |
| `POST /query` | Natural language question to the AI agent |

`/query` accepts questions up to 500 characters, allows 10 requests per minute and caches repeated questions for 10 minutes.

---

## Dashboard

A single-page industrial control room interface built in vanilla HTML/CSS/JS. Three views:

- **Command Center** - Live machine status cards with risk scores, energy costs, efficiency flags, and operational recommendations
- **AI Query Interface** - Chat-style interface for asking questions in plain English
- **Pipeline Health** - Data quality breakdown and governance metrics

---

## Tech Stack

- **Language:** Python 3.12
- **Data:** Pandas, SQLAlchemy, SQLite
- **AI:** LangChain 1.2 (`create_agent`, built on LangGraph), Groq, Ollama
- **Protocol:** Model Context Protocol (Python SDK, stdio and Streamable HTTP)
- **Observability:** Langfuse, LangSmith
- **API:** FastAPI, Uvicorn
- **Deployment:** Docker, Railway
- **Version Control:** Git

---

## Running It

**Clone and install:**
```bash
git clone https://github.com/gitesh-kumar/Industrial_Data_Pipeline.git
cd Industrial_Data_Pipeline
pip install -r requirements.txt
```

**Set up environment:**
```bash
cp .env.example .env
```
Then set these values in `.env`:

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY`, `GROQ_MODEL` | Cloud mode model |
| `AI_MODE` | `cloud` (default) or `local` |
| `OLLAMA_MODEL` | Local mode model, for example `llama3.1` |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | Langfuse tracing (optional) |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_ENDPOINT`, `LANGSMITH_PROJECT` | LangSmith tracing (optional) |

Never commit `.env`. It is listed in `.gitignore`.

**Run the pipeline to populate the database:**
```bash
python main.py
```

**Start the API:**
```bash
python -m uvicorn api:app --reload
```

**Ask a question from the terminal:**
```bash
python ai_assistant.py
```

**Run the tests:**
```bash
python -m pytest tests -q
```

**Or run with Docker:**
```bash
docker build -t industrial-pipeline .
docker run -p 8000:8000 --env-file .env industrial-pipeline
```

**Live demo:** https://industrialdatapipeline.up.railway.app/dashboard

---

## Why This Design

The first version of the AI layer was an intent router. It sorted each question into one of eight fixed intents and ran a prewritten query. It was cheap and predictable, but it gave no answer whenever the wording did not match an intent, and it could not reason about anything the data did not hold directly.

The current design keeps what was good about it and drops the limit. The model writes the SQL, so the wording no longer matters. A guard that is plain code decides what may run, so a wrong query cannot change anything. The prompt teaches a method for questions the data cannot answer directly, and the answer says when it is an inference. Every run is traced, and a test set grades the behavior, so a change to the prompt or the model shows up as a number and not as a feeling.
