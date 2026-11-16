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


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Factory data MCP server</title>
<style>
body{font:16px/1.55 system-ui,sans-serif;max-width:760px;margin:2.5rem auto;padding:0 1rem;color:#1b1f23}
h1{font-size:1.5rem;margin:0 0 .4rem} h2{font-size:1.05rem;margin:2rem 0 .5rem}
code,pre,textarea{font:13.5px/1.5 ui-monospace,Consolas,monospace}
code{background:#eef0f2;padding:.1rem .3rem;border-radius:3px}
pre{background:#14181c;color:#e6e9ec;padding:.9rem;border-radius:6px;overflow:auto;max-height:340px;white-space:pre-wrap;word-break:break-word}
textarea{width:100%;box-sizing:border-box;padding:.6rem;border:1px solid #b9c0c7;border-radius:6px}
button{font:inherit;padding:.45rem .9rem;margin:.3rem .4rem .3rem 0;border:1px solid #1b1f23;background:#fff;border-radius:6px;cursor:pointer}
button:hover{background:#1b1f23;color:#fff}
.small{color:#566069;font-size:.92rem}
</style></head><body>
<h1>Factory data MCP server</h1>
<p>This is a live <a href="https://modelcontextprotocol.io">Model Context Protocol</a> server for a simulated factory with 17 machines.
An MCP client such as Claude Desktop connects to <code id="url"></code> and can then call the tools below.
The data is simulated and every tool is read-only. Each query passes a SQL guard that opens the database read-only and allows a single SELECT.</p>
<h2>Try it</h2>
<p class="small">The buttons send real MCP requests (JSON-RPC over HTTP) from your browser to this server. The black box shows the request and the answer.</p>
<button id="b1">1. List the tools</button>
<button id="b2">2. Describe the database</button>
<button id="b3">3. Run the query below</button>
<button id="b4">4. Try to delete data</button>
<textarea id="q" rows="3">SELECT machine_id, machine_type, max_temp, temp_warn_c, efficiency_status FROM gold_operations_status ORDER BY max_temp DESC LIMIT 5</textarea>
<pre id="out">Press a button.</pre>
<h2>Connect your own client</h2>
<p>Add this address as a remote MCP server (transport: Streamable HTTP): <code id="url2"></code></p>
<script>
const URL_ = location.origin + "/mcp";
document.getElementById("url").textContent = URL_; document.getElementById("url2").textContent = URL_;
const out = document.getElementById("out"); let n = 0;
async function rpc(method, params) {
  const body = {jsonrpc: "2.0", id: ++n, method: method, params: params || {}};
  out.textContent = "Sending...\\n" + JSON.stringify(body, null, 2);
  try {
    const r = await fetch("/mcp", {method: "POST", body: JSON.stringify(body),
      headers: {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}});
    let t = await r.text();
    const m = t.match(/^data: (.*)$/m); if (m) t = m[1];
    try { t = JSON.stringify(JSON.parse(t), null, 2); } catch (e) {}
    out.textContent = "REQUEST\\n" + JSON.stringify(body, null, 2) + "\\n\\nRESPONSE (HTTP " + r.status + ")\\n" + t;
  } catch (e) { out.textContent = "Request failed: " + e; }
}
const call = (name, args) => rpc("tools/call", {name: name, arguments: args});
document.getElementById("b1").onclick = () => rpc("tools/list");
document.getElementById("b2").onclick = () => call("describe_database", {});
document.getElementById("b3").onclick = () => call("run_sql", {query: document.getElementById("q").value});
document.getElementById("b4").onclick = () => call("run_sql", {query: "DELETE FROM gold_operations_status"});
</script></body></html>"""


@server.custom_route("/", methods=["GET"])
async def home(request):
    from starlette.responses import HTMLResponse
    return HTMLResponse(PAGE)


if WITH_ASK:
    server.tool(annotations=READ_ONLY)(ask_factory)


if __name__ == "__main__":
    if HTTP:          # Railway: a web server on a URL, e.g. https://<app>.up.railway.app/mcp
        server.run("streamable-http", host="0.0.0.0", port=int(os.getenv("PORT", "8000")),
                   stateless_http=True, json_response=True)   # no session handshake, so the page above can call it
    else:             # stdio: the host starts this program and talks to it through its input and output
        server.run()
