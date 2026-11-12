"""
Question in plain English -> SQL -> rows -> short answer.

  1. The model gets the data dictionary and the question and writes ONE
     SQL query. It never sees the data itself.
  2. sql_guard runs the query read-only. On an error or an empty result the
     model gets one more try, with the problem named.
  3. The model turns the returned rows into 1 to 3 sentences.
     No rows means no model call: the answer says so.

AI_MODE=local uses Ollama on this machine. Anything else uses Groq.
"""
import json
import logging
import os
import re
import sys

from dotenv import load_dotenv

import data_dictionary
from sql_guard import SQLGuardError, run_readonly

load_dotenv()
log = logging.getLogger("assistant")

DB_PATH = os.getenv("DB_PATH", "factory_lakehouse.db")
AI_MODE = "local" if os.getenv("AI_MODE", "cloud") == "local" else "cloud"

_llm = None


def get_llm():
    global _llm
    if _llm is None:
        if AI_MODE == "local":
            from langchain_ollama import OllamaLLM
            _llm = OllamaLLM(model="llama3", temperature=0)
        else:
            from langchain_groq import ChatGroq
            _llm = ChatGroq(
                model=os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"),
                groq_api_key=os.getenv("GROQ_API_KEY"),
                temperature=0,
                max_tokens=512,
                reasoning_effort="none",
            )
    return _llm


def set_llm(llm):
    """Swap the model, used by the tests."""
    global _llm
    _llm = llm


def _call(prompt: str) -> str:
    resp = get_llm().invoke(prompt)
    content = getattr(resp, "content", resp)
    if isinstance(content, list):
        content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content)


# ── PROMPTS ─────────────────────────────────────────────────────────────
SQL_INSTRUCTIONS = """You write one SQLite query that answers the user's question.
Use only the tables, columns and values described below.

Reply with the SQL query only. No explanation, no markdown.
If the data cannot answer the question, reply with CANNOT_ANSWER: and one short reason.

Rules for the query:
- One SELECT statement.
- Use the exact value spellings listed under VALUES.
- Name the columns so the result is easy to read, and ROUND decimals to 2 places.
- Add LIMIT when the question asks for the top or the first few.
"""

ANSWER_INSTRUCTIONS = """Answer the question using only the rows below.
- Use only machine ids and numbers that appear in the rows.
- Do not add causes, advice or facts that the rows do not show.
- Write 1 to 3 plain sentences. Give units where the column name implies one
  (kW, degrees C, EUR per hour).
"""


def _sql_prompt(question: str, feedback: str = "") -> str:
    p = f"{SQL_INSTRUCTIONS}\n{data_dictionary.render_context()}\nQuestion: {question}\n"
    if feedback:
        p += f"\n{feedback}\n"
    return p + "Answer:"


def _answer_prompt(question: str, sql: str, result: dict) -> str:
    note = "\nOnly the first rows are shown. Say so." if result["truncated"] else ""
    return (f"{ANSWER_INSTRUCTIONS}{note}\n"
            f"Question: {question}\nSQL: {sql}\n"
            f"Rows (JSON): {json.dumps(result['rows'], default=str)}\n\nAnswer:")


# ── CLEANING WHAT THE MODEL SENDS BACK ──────────────────────────────────
def clean_sql(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fence = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.S | re.I)
    if fence:
        text = fence.group(1).strip()
    if not text.upper().startswith("CANNOT_ANSWER"):
        start = re.search(r"\b(select|with)\b", text, flags=re.I)
        if start:
            text = text[start.start():]
    return text.strip().rstrip(";").strip()


def plain_rows(result: dict) -> str:
    """Used when the model cannot be reached for the last step."""
    parts = [", ".join(f"{k}: {v}" for k, v in row.items()) for row in result["rows"][:10]]
    return "; ".join(parts)


# ── MAIN ENTRY ──────────────────────────────────────────────────────────
def answer(question: str) -> dict:
    allowed = data_dictionary.allowed_tables()
    sqls, steps = [], 0
    feedback = ""
    result = None

    for attempt in (1, 2):
        text = clean_sql(_call(_sql_prompt(question, feedback)))
        steps += 1

        if text.upper().startswith("CANNOT_ANSWER"):
            reason = text[len("CANNOT_ANSWER"):].lstrip(": ").strip()
            return {"answer": reason or "The data cannot answer that question.",
                    "sql_queries_used": sqls, "rows": [], "total_steps": steps,
                    "refused": True}

        sqls.append(text)
        try:
            result = run_readonly(text, DB_PATH, allowed)
        except SQLGuardError as e:
            log.warning("attempt %d rejected: %s | %s", attempt, e, text)
            feedback = f"Your previous query:\n{text}\nProblem: {e}\nWrite a corrected query."
            result = None
            continue
        if not result["rows"]:
            feedback = (f"Your previous query:\n{text}\nIt returned no rows. Check the exact "
                        "spellings under VALUES and the table you used, then write a corrected query.")
            continue
        break

    if result is None:
        return {"answer": "I could not build a valid query for that question. Try asking it differently.",
                "sql_queries_used": sqls, "rows": [], "total_steps": steps, "refused": False}
    if not result["rows"]:
        return {"answer": "No data matches that question.",
                "sql_queries_used": sqls, "rows": [], "total_steps": steps, "refused": False}

    try:
        text_answer = _call(_answer_prompt(question, sqls[-1], result)).strip()
        steps += 1
    except Exception as e:
        log.warning("answer step failed: %s", e)
        text_answer = plain_rows(result)

    return {"answer": text_answer, "sql_queries_used": sqls, "rows": result["rows"][:20],
            "total_steps": steps, "refused": False}


def ask(question: str) -> str:
    return answer(question)["answer"]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    print(f"INDUSTRIAL AGENT READY ({AI_MODE})  type 'exit' to quit")
    while True:
        q = input("\n[Query]: ").strip()
        if q.lower() in ("exit", "quit"):
            break
        if not q:
            continue
        try:
            r = answer(q)
            for s in r["sql_queries_used"]:
                print(f"\nSQL: {s}")
            print(f"\nAI Response: {r['answer']}")
        except Exception as e:
            print(f"\nError: {e}")
