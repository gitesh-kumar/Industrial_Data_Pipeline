"""
MCP server for the factory data.

Any MCP host (Claude Desktop, Cursor, another agent) can connect to this and use
three tools:

  describe_database   the tables, columns, values and rules (text)
  run_sql             one read-only SELECT, through sql_guard
  ask_factory         the whole assistant: question in, answer out

Everything is read-only. sql_guard opens the database read-only and checks every
query, so a host or model that misbehaves still cannot change anything.

Run it by hand to check it starts (it then waits for a host, stop it with Ctrl+C):

    python mcp_server.py

A host starts it itself. See the README note for the Claude Desktop setting.
Nothing in this file may print to standard output, that is where the protocol talks.
"""
import os
import time
from collections import deque

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

import data_dictionary
from sql_guard import SQLGuardError, run_readonly

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

# A host starts this from its own folder, so the path must not depend on where we are.
DB_PATH = os.getenv("DB_PATH") or os.path.join(HERE, "factory_lakehouse.db")

server = MCPServer(
    "industrial-factory",
    instructions=("Simulated factory with 17 machines. Call describe_database first to learn the "
                  "tables and columns. All tools are read-only."),
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False)


@server.tool(annotations=READ_ONLY)
def describe_database() -> str:
    """Describe the factory database: its tables, what each column means, the allowed values and the rules for reading the data. Call this before writing a query."""
    return data_dictionary.render_context()


@server.tool(annotations=READ_ONLY)
def run_sql(query: str) -> dict:
    """Run one read-only SQLite SELECT query on the factory database and return the columns and rows (at most 50). If it returns an error, read the message and send a corrected query."""
    try:
        return run_readonly(query, DB_PATH, data_dictionary.allowed_tables())
    except SQLGuardError as e:
        return {"error": str(e)}


# Over HTTP the URL is public, and this tool spends model quota, so it is off there unless MCP_ASK=1.
HTTP = os.getenv("MCP_TRANSPORT", "stdio") == "http"
WITH_ASK = (not HTTP) or os.getenv("MCP_ASK") == "1"


MAX_QUESTION = 500           # same limits as the /query endpoint in api.py
CACHE_SECONDS = 600
CALLS_PER_MINUTE = 10
_cache = {}                 # question -> (time, result)
_calls = deque()            # times of recent model calls, for everybody together


def ask_factory(question: str) -> dict:
    """Ask a question about the factory in plain English. An AI assistant writes and runs the queries itself and answers in a few sentences. If the data has no exact column for the question, it uses the closest measurements and says that its answer is an inference."""
    question = question.strip()
    if not question or len(question) > MAX_QUESTION:
        return {"error": f"Send a question of 1 to {MAX_QUESTION} characters."}
    now = time.monotonic()
    hit = _cache.get(question)
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]                                  # a repeated question costs no model call
    while _calls and now - _calls[0] > 60:
        _calls.popleft()
    if len(_calls) >= CALLS_PER_MINUTE:
        return {"error": "Too many questions right now. Try again in a minute."}
    _calls.append(now)
    import ai_assistant            # loaded here so the other two tools start without the model libraries
    ai_assistant.DB_PATH = DB_PATH
    r = ai_assistant.answer(question)
    result = {"answer": r["answer"], "sql_queries_used": r["sql_queries_used"], "rows": r["rows"]}
    if not r.get("degraded"):
        _cache[question] = (now, result)               # a failed model call is not remembered
    return result


if WITH_ASK:
    server.tool(annotations=READ_ONLY)(ask_factory)


if __name__ == "__main__":
    if HTTP:          # Railway: a web server on a URL, e.g. https://<app>.up.railway.app/mcp
        server.run("streamable-http", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
    else:             # stdio: the host starts this program and talks to it through its input and output
        server.run()
