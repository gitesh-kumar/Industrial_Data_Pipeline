import os
import time
from collections import OrderedDict, defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

load_dotenv()

app = FastAPI(
    title="Industrial AI Pipeline API",
    description="REST API for the Smart Factory Data Lakehouse (simulated data)",
    version="1.1.0"
)


@app.get("/dashboard")
def dashboard():
    static_path = os.path.join(os.path.dirname(__file__), "static", "dashboard.html")
    return FileResponse(static_path)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ── LIMITS FOR /query ────────────────────────────────────────────
# Every /query call can spend Groq quota, and the endpoint is public.
# Two small guards, both in memory (one process, resets on restart):
#   1. per IP: at most RATE_LIMIT calls per RATE_WINDOW seconds
#   2. identical question inside CACHE_TTL seconds: reuse the last answer
RATE_LIMIT = 10
RATE_WINDOW = 60
CACHE_TTL = 600
CACHE_MAX = 200

_calls = defaultdict(deque)
_cache = OrderedDict()


def client_ip(request: Request) -> str:
    # Railway puts the real client address in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(ip: str):
    now = time.time()
    q = _calls[ip]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Too many questions. Limit is {RATE_LIMIT} per minute."
        )
    q.append(now)


def cache_get(question: str):
    hit = _cache.get(question)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    return None


def cache_put(question: str, answer: str):
    _cache[question] = (time.time(), answer)
    _cache.move_to_end(question)
    while len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)


def get_agent():
    from ai_assistant import answer
    return answer


class QueryRequest(BaseModel):
    question: str


@app.get("/")
def root():
    return {
        "status": "running",
        "project": "Industrial Data Pipeline API (simulated data)",
        "mode": os.getenv("AI_MODE", "cloud_agent"),
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

@app.get("/energy")
def energy():
    try:
        from src.energy_costs import compute_energy
        return compute_energy()
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/maintenance")
def maintenance():
    try:
        from src.board import maintenance_list
        return maintenance_list()
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/machines/{machine_id}/history")
def machine_history(machine_id: str):
    try:
        from src.board import machine_history as history
        return history(machine_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pipeline/health")
def pipeline_health():
    try:
        from src.data_governance import compute_quality
        q = compute_quality()
        return {
            # kept for the current dashboard
            "health_score_percent": q["data_quality_score_percent"],
            "breakdown": q["machine_events"],
            "status": q["status"],
            # new, separate numbers
            "data_quality": {
                "rows": q["rows"],
                "null_rows": q["null_rows"],
                "duplicate_rows": q["duplicate_rows"],
                "out_of_range_rows": q["out_of_range_rows"],
                "latest_reading": q["latest_reading"],
            },
            "event_rate_percent": q["event_rate_percent"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query")
def query_agent(body: QueryRequest, request: Request):
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty.")
    if len(question) > 500:
        raise HTTPException(status_code=400, detail="Question is too long (max 500 characters).")

    cached = cache_get(question)
    if cached is not None:
        return {**cached, "question": question, "cached": True}

    check_rate_limit(client_ip(request))

    try:
        result = get_agent()(question)
        cache_put(question, result)
        return {**result, "question": question, "cached": False}
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "rate_limit" in error_str.lower():
            raise HTTPException(status_code=429, detail="Rate limit reached. Please wait a few minutes and try again.")
        elif "401" in error_str or "auth" in error_str.lower():
            raise HTTPException(status_code=401, detail="Authentication error. Please check server configuration.")
        else:
            raise HTTPException(status_code=500, detail="An error occurred processing your request. Please try again.")
