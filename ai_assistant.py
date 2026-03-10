from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_ollama import OllamaLLM

# 1. Database Connection
db = SQLDatabase.from_uri("sqlite:///factory_lakehouse.db")

# 2. The Model (Llama 3)
llm = OllamaLLM(model="llama3", temperature=0)

# 3. Create a ReAct Agent (Better for Local Models)
# We remove 'agent_type' so it defaults to a style Llama can handle
agent_executor = create_sql_agent(
    llm, 
    db=db, 
    verbose=True,
    handle_parsing_errors=True # Crucial for local models!
)

print("\n🚀 LOCAL INDUSTRIAL AGENT READY")

while True:
    user_query = input("\n[Query]: ")
    if user_query.lower() in ['exit', 'quit']: break
    
    # Keeping the prompt simple helps the local model not get confused
    try:
        response = agent_executor.invoke({"input": user_query})
        print(f"\nAI Response: {response['output']}")
    except Exception as e:
        # If the model gets stuck in a loop, we catch it here
        print(f"\nModel is thinking too hard! Try rephrasing. Error: {e}")