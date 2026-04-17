import os
from dotenv import load_dotenv
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent

load_dotenv()

db = db = SQLDatabase.from_uri(
    "sqlite:///factory_lakehouse.db",
    include_tables=["gold_operations_status"]
)

def select_mode():
    print("\n" + "="*50)
    print("🏭 INDUSTRIAL AI AGENT - SELECT MODE")
    print("="*50)
    print("1. Local mode  (Ollama/Llama3) — data stays on-premise")
    print("2. Cloud mode  (Groq/Llama3)   — scalable deployment")
    print("="*50)
    
    while True:
        choice = input("Select mode (1 or 2): ").strip()
        if choice in ['1', '2']:
            return 'local' if choice == '1' else 'cloud'
        print("Invalid choice. Please enter 1 or 2.")

# Check if running as API (no interactive input) or standalone
AI_MODE = os.getenv("AI_MODE", None)

if AI_MODE is None:
    AI_MODE = select_mode()

if AI_MODE == "local":
    from langchain_ollama import OllamaLLM
    llm = OllamaLLM(model="llama3", temperature=0)
    print("🖥️  Running in LOCAL mode (Ollama/Llama3) — data stays on-premise")
else:
    from langchain_groq import ChatGroq
    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0
    )
    print("☁️  Running in CLOUD mode (Groq/Llama3) — scalable deployment")

agent_executor = create_sql_agent(
    llm,
    db=db,
    verbose=True,
    handle_parsing_errors=True
)

if __name__ == "__main__":
    print("\n🚀 INDUSTRIAL AGENT READY")
    while True:
        user_query = input("\n[Query]: ")
        if user_query.lower() in ['exit', 'quit']:
            break
        try:
            response = agent_executor.invoke({"input": user_query})
            print(f"\nAI Response: {response['output']}")
        except Exception as e:
            print(f"\nError: {e}")