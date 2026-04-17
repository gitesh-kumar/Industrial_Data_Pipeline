import os
import json
from dotenv import load_dotenv
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from sqlalchemy import create_engine, text

load_dotenv()

db = SQLDatabase.from_uri("sqlite:///factory_lakehouse.db")
engine = create_engine("sqlite:///factory_lakehouse.db")

# ── PRE-WRITTEN SQL QUERIES ──────────────────────────────────────
INTENT_QUERIES = {
    "highest_cost": """
        SELECT machine_id, machine_type, hourly_energy_cost_eur, recommendation
        FROM gold_operations_status
        ORDER BY hourly_energy_cost_eur DESC LIMIT 3
    """,
    "highest_risk": """
        SELECT machine_id, machine_type, avg_risk_score, max_risk_score, efficiency_status
        FROM gold_operations_status
        ORDER BY avg_risk_score DESC LIMIT 3
    """,
    "needs_maintenance": """
        SELECT machine_id, machine_type, recommendation, failure_spike_count, degradation_count, avg_risk_score
        FROM gold_operations_status
        WHERE recommendation != 'CONTINUE'
        ORDER BY avg_risk_score DESC
    """,
    "fleet_overview": """
        SELECT 
            COUNT(*) as total_machines,
            SUM(hourly_energy_cost_eur) as total_hourly_cost,
            AVG(avg_risk_score) as fleet_avg_risk,
            SUM(failure_spike_count) as total_failure_spikes,
            COUNT(CASE WHEN recommendation != 'CONTINUE' THEN 1 END) as machines_needing_attention
        FROM gold_operations_status
    """,
    "efficiency_status": """
        SELECT machine_id, machine_type, efficiency_status, avg_temp, avg_power_usage, recommendation
        FROM gold_operations_status
        ORDER BY efficiency_status DESC, avg_temp DESC
    """,
    "failure_spikes": """
        SELECT machine_id, machine_type, failure_spike_count, degradation_count, avg_risk_score, recommendation
        FROM gold_operations_status
        WHERE failure_spike_count > 0 OR degradation_count > 0
        ORDER BY failure_spike_count DESC
    """,
    "compare_types": """
        SELECT 
            SUBSTR(machine_type, 1, INSTR(machine_type || '_', '_') - 1) as type_group,
            COUNT(*) as count,
            AVG(avg_risk_score) as avg_risk,
            AVG(hourly_energy_cost_eur) as avg_cost,
            SUM(failure_spike_count) as total_failures
        FROM gold_operations_status
        GROUP BY type_group
        ORDER BY avg_risk DESC
    """,
    "highest_loss": """
        SELECT machine_id, machine_type, hourly_energy_cost_eur, avg_risk_score, 
               failure_spike_count, recommendation
        FROM gold_operations_status
        ORDER BY hourly_energy_cost_eur DESC LIMIT 3
    """
}

INTENT_KEYWORDS = {
    "highest_cost": ["cost", "expensive", "energy", "power", "electricity", "euro", "eur"],
    "highest_risk": ["risk", "dangerous", "unsafe", "critical", "risk score"],
    "needs_maintenance": ["maintenance", "repair", "fix", "shutdown", "attention", "problem"],
    "fleet_overview": ["overview", "overall", "fleet", "factory", "summary", "total", "all machines"],
    "efficiency_status": ["efficient", "inefficient", "efficiency", "temperature", "optimal", "warning"],
    "failure_spikes": ["failure", "spike", "breakdown", "fault", "degradation", "failed"],
    "compare_types": ["compare", "vs", "versus", "difference", "compressor", "turbine", "pump", "motor", "generator"],
    "highest_loss": ["loss", "losing", "highest loss", "most loss", "worst"]
}

def detect_intent(question: str) -> str:
    question_lower = question.lower()
    scores = {intent: 0 for intent in INTENT_KEYWORDS}
    for intent, keywords in INTENT_KEYWORDS.items():
        for keyword in keywords:
            if keyword in question_lower:
                scores[intent] += 1
    best_intent = max(scores, key=scores.get)
    if scores[best_intent] == 0:
        return "fleet_overview"
    return best_intent

def run_fast_query(question: str, llm) -> str:
    intent = detect_intent(question)
    query = INTENT_QUERIES[intent]
    
    with engine.connect() as conn:
        result = conn.execute(text(query))
        rows = [dict(row._mapping) for row in result]
    
    prompt = f"""You are an industrial AI assistant analyzing factory machine data.

Question: {question}
Intent detected: {intent}
Query results: {json.dumps(rows, indent=2)}

Give a clear, concise answer in 2-3 sentences. Focus on the most important insight.
Start directly with the answer, no preamble."""

    # Handle both Ollama and Groq response formats
    try:
        response = llm.invoke(prompt)
        if hasattr(response, 'content'):
            return response.content
        return str(response)
    except Exception:
        response = llm(prompt)
        return str(response)

# ── MODE SELECTION ───────────────────────────────────────────────
def select_mode():
    print("\n" + "="*50)
    print("🏭 INDUSTRIAL AI AGENT - SELECT MODE")
    print("="*50)
    print("1. Local mode        (Ollama/Llama3)  — on-premise")
    print("2. Cloud Fast mode   (Groq/Intent)    — reliable & cheap")
    print("3. Cloud Agent mode  (Groq/ReAct)     — flexible & powerful")
    print("="*50)
    
    while True:
        choice = input("Select mode (1, 2 or 3): ").strip()
        if choice in ['1', '2', '3']:
            modes = {'1': 'local', '2': 'cloud_fast', '3': 'cloud_agent'}
            return modes[choice]
        print("Invalid choice. Please enter 1, 2 or 3.")

AI_MODE = os.getenv("AI_MODE", None)
if AI_MODE is None:
    AI_MODE = select_mode()

# ── LLM SETUP ────────────────────────────────────────────────────
if AI_MODE == "local":
    from langchain_ollama import OllamaLLM
    llm = OllamaLLM(model="llama3", temperature=0)
    print("🖥️  LOCAL mode (Ollama/Llama3) — data stays on-premise")
    agent_executor = None
elif AI_MODE == "cloud_fast":
    from langchain_groq import ChatGroq
    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0,
        max_tokens=512
    )
    print("⚡ CLOUD FAST mode (Groq/Intent Router) — reliable & cheap")
    agent_executor = None
else:
    from langchain_groq import ChatGroq
    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0,
        max_tokens=1024
    )
    print("☁️  CLOUD AGENT mode (Groq/ReAct) — flexible & powerful")
    agent_executor = create_sql_agent(
        llm, db=db, verbose=False,
        handle_parsing_errors=True,
        max_iterations=15, max_execution_time=120
    )

def ask(question: str) -> str:
    if AI_MODE == "local" or AI_MODE == "cloud_fast":
        return run_fast_query(question, llm)
    else:
        response = agent_executor.invoke({"input": question})
        output = response.get('output', '')
        if 'Agent stopped' in output:
            steps = response.get('intermediate_steps', [])
            if steps:
                return f"Based on the data: {steps[-1][1]}"
        return output

if __name__ == "__main__":
    print("\n🚀 INDUSTRIAL AGENT READY")
    while True:
        user_query = input("\n[Query]: ")
        if user_query.lower() in ['exit', 'quit']:
            break
        try:
            print(f"\nAI Response: {ask(user_query)}")
        except Exception as e:
            print(f"\nError: {e}")