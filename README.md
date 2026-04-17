# Industrial IoT Predictive Maintenance System
### AI-Powered Financial Risk Engine for Factory Operations

---

## What This Project Does

This system monitors factory machinery in real-time and translates raw sensor data into financial risk. It tells you not just that a machine is running hot but exactly how much that is costing you per hour, and whether you should shut it down.

I built this because I spent 4 years at Hindustan Petroleum Corporation working with SCADA systems and watching engineers make critical decisions based on Excel sheets pulled manually from plant historians. This project automates that entire workflow.

---

## Architecture

The pipeline follows the **Medallion Architecture** used by companies like Databricks and Microsoft for production data lakes:

**Bronze Layer** - Raw ingestion. Seventeen factory machines (turbines, pumps, compressors, motors, generators, heat exchangers) generate sensor telemetry every 3 seconds. Vibration, temperature, and power consumption are captured and appended to a time-series store. Anomaly spikes are injected probabilistically to simulate real failure events.

**Silver Layer** - Cleaning and validation. Raw data is deduplicated, quality-flagged (PASS, HIGH_TEMP_WARN, VIBRATION_CRITICAL, FAILURE_SPIKE, DEGRADATION_WARN), unit-converted, and enriched with a composite risk score before being loaded into a structured SQL table.

**Gold Layer** - Business intelligence. Live energy market pricing (simulating German peak/off-peak electricity rates) is applied to each machine's power consumption to calculate hourly energy cost in euros. Machines are classified by efficiency status and given operational recommendations (CONTINUE, REDUCE_LOAD, SCHEDULE_MAINTENANCE, IMMEDIATE_SHUTDOWN).

**Governance Layer** - Automated pipeline health scoring. Every run calculates a data quality percentage and flags degradation in sensor reliability.

---

## The AI Layer

This is where it gets interesting. The system supports three inference modes, each designed for a different deployment context:

**Local Mode (Ollama + Llama3)** - Runs entirely on-premise. No data leaves the machine. Designed for environments where operational data is sensitive and cannot be sent to external cloud providers. This is the reality in most industrial settings like refineries, power plants, and manufacturing facilities cannot use SaaS AI tools due to data sovereignty requirements.

**Cloud Fast Mode (Groq + Intent Router)** - A production-grade architecture where the AI classifies the user's question into one of eight predefined intents, executes a pre-written SQL query, and uses the LLM only to format a natural language response. Two LLM calls total. This approach is 10x cheaper than an open-ended agent, eliminates infinite loop failures, and scales to datasets of any size.

**Cloud Agent Mode (Groq + ReAct)** - A LangChain SQL agent that autonomously writes and executes SQL queries for exploratory analysis. Powerful for ad-hoc questions but token-intensive. Included to demonstrate the architectural tradeoff and because knowing *when not* to use an agent is as important as knowing how to build one.

The dual architecture is not an accident. It reflects a real decision engineers face: data sovereignty vs. scalability. This system lets you choose.

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

---

## Dashboard

A single-page industrial control room interface built in vanilla HTML/CSS/JS. Three views:

- **Command Center** — Live machine status cards with risk scores, energy costs, efficiency flags, and operational recommendations
- **AI Query Interface** — Chat-style interface for asking questions in plain English
- **Pipeline Health** — Data quality breakdown and governance metrics

---

## Tech Stack

- **Language:** Python 3.12
- **Data:** Pandas, SQLAlchemy, SQLite
- **AI:** LangChain, Ollama, Groq, Llama 3.3 70B
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
# Add your GROQ_API_KEY to .env
```

**Run the pipeline to populate the database:**
```bash
python main.py
```

**Start the API:**
```bash
python -m uvicorn api:app --reload
```

**Or run with Docker:**
```bash
docker build -t industrial-pipeline .
docker run -p 8000:8000 --env-file .env industrial-pipeline
```

**Live demo:** https://industrialdatapipeline.up.railway.app/dashboard

---

## Why This Architecture Matters

Most AI projects query a database and return an answer. This one makes an architectural decision about *how* to query and explains why. The intent router exists because I hit the limitations of open-ended agents at scale and redesigned the system around those constraints. That is what production engineering looks like.
