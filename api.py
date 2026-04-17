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

def get_agent():
    global agent_executor
    if agent_executor is None:
        from ai_assistant import agent_executor as _agent
        agent_executor = _agent
    return agent_executor

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
        agent = get_agent()
        response = agent.invoke({"input": request.question})

        sql_queries = []
        for step in response.get("intermediate_steps", []):
            try:
                action, observation = step
                if hasattr(action, 'tool') and action.tool == 'sql_db_query':
                    sql_queries.append(str(action.tool_input))
            except:
                pass

        return {
            "question": request.question,
            "answer": response["output"],
            "sql_queries_used": sql_queries,
            "total_steps": len(response.get("intermediate_steps", []))
        }

    except Exception as e:
        error_str = str(e)
        # Return clean error messages — never expose API keys or org details
        if "429" in error_str or "rate_limit" in error_str.lower():
            raise HTTPException(status_code=429, detail="Rate limit reached. Please wait a few minutes and try again.")
        elif "401" in error_str or "auth" in error_str.lower():
            raise HTTPException(status_code=401, detail="Authentication error. Please check server configuration.")
        else:
            raise HTTPException(status_code=500, detail="An error occurred processing your request. Please try again.")