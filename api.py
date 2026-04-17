import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

load_dotenv()

app = FastAPI(
    title="Industrial AI Pipeline API",
    description="REST API for the Smart Factory Data Lakehouse",
    version="1.0.0"
)

@app.get("/dashboard")
def dashboard():
    return FileResponse("static/dashboard.html")

app.mount("/static", StaticFiles(directory="static"), name="static")

agent_executor = None
llm_instance = None

def get_agent():
    global agent_executor, llm_instance
    if agent_executor is None and llm_instance is None:
        from ai_assistant import agent_executor as _agent, llm as _llm
        agent_executor = _agent
        llm_instance = _llm
    from ai_assistant import ask
    return ask

class QueryRequest(BaseModel):
    question: str

@app.get("/")
def root():
    return {
        "status": "running",
        "project": "Industrial IoT Predictive Maintenance System",
        "mode": os.getenv("AI_MODE", "cloud"),
        "docs": "/docs"
    }

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/machines")
def get_machines():
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine("sqlite:///factory_lakehouse.db")
        with engine.connect() as conn:
            result = conn.execute(text("SELECT * FROM gold_operations_status"))
            rows = [dict(row._mapping) for row in result]
        return {"machines": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/machines/{machine_id}/risk")
def get_machine_risk(machine_id: str):
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine("sqlite:///factory_lakehouse.db")
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM gold_operations_status WHERE machine_id = :id"),
                {"id": machine_id}
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Machine {machine_id} not found")
            return dict(row._mapping)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pipeline/health")
def pipeline_health():
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine("sqlite:///factory_lakehouse.db")
        with engine.connect() as conn:
            query = "SELECT quality_flag, COUNT(*) as count FROM silver_telemetry GROUP BY quality_flag"
            result = conn.execute(text(query))
            rows = [dict(row._mapping) for row in result]
            total = sum(r['count'] for r in rows)
            passed = next((r['count'] for r in rows if r['quality_flag'] == 'PASS'), 0)
            health_score = round((passed / total) * 100, 2) if total > 0 else 0
        return {
            "health_score_percent": health_score,
            "breakdown": rows,
            "status": "HEALTHY" if health_score >= 90 else "WARNING"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query")
def query_agent(request: QueryRequest):
    try:
        ask = get_agent()
        answer = ask(request.question)
        return {
            "question": request.question,
            "answer": answer
        }
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "rate_limit" in error_str.lower():
            raise HTTPException(status_code=429, detail="Rate limit reached. Please wait a few minutes and try again.")
        elif "401" in error_str or "auth" in error_str.lower():
            raise HTTPException(status_code=401, detail="Authentication error. Please check server configuration.")
        elif "iteration limit" in error_str.lower() or "time limit" in error_str.lower():
            raise HTTPException(status_code=500, detail="Query too complex. Try rephrasing with a more specific question.")
        else:
            raise HTTPException(status_code=500, detail="An error occurred processing your request. Please try again.")