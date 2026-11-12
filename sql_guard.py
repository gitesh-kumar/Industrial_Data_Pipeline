"""
Runs SQL that a language model wrote, and makes sure it can only read.

Four layers, each one enough to stop a write on its own:
  1. The database is opened read-only (SQLite mode=ro).
  2. SQLite asks an authorizer about every table and function the statement
     touches. Anything outside the allowed tables is denied. This is checked
     by SQLite itself while it prepares the statement, so it cannot be fooled
     by odd spacing, comments or quoting the way a text filter can.
  3. Only one statement is allowed, and it must start with SELECT or WITH.
  4. A time limit stops runaway queries, and a row cap limits the output.
"""
import sqlite3
import time
from pathlib import Path

MAX_SQL_CHARS = 2000
MAX_ROWS = 50
TIMEOUT_SECONDS = 3.0

# Numbers from the SQLite C interface (action codes for the authorizer).
_SQLITE_READ = 20
_SQLITE_SELECT = 21
_SQLITE_FUNCTION = 31
_SQLITE_RECURSIVE = 33

_DENIED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}


class SQLGuardError(Exception):
    """The SQL broke a rule. The message is safe to show and to give back to the model."""


def run_readonly(sql: str, db_path: str, allowed_tables: set,
                 max_rows: int = MAX_ROWS, timeout: float = TIMEOUT_SECONDS) -> dict:
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise SQLGuardError("The query is empty.")
    if len(sql) > MAX_SQL_CHARS:
        raise SQLGuardError("The query is too long.")
    if sql.split(None, 1)[0].lower() not in ("select", "with"):
        raise SQLGuardError("Only a single SELECT query is allowed.")

    allowed = {t.lower() for t in allowed_tables}
    denied = []

    def authorizer(action, arg1, arg2, dbname, source):
        if action in (_SQLITE_SELECT, _SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == _SQLITE_READ:
            # A read with no database name is a WITH clause or a subquery
            # result, not a stored table. Every stored table, including
            # sqlite_master, is reported with its database name ('main').
            if dbname is None:
                return sqlite3.SQLITE_OK
            if (arg1 or "").lower() in allowed:
                return sqlite3.SQLITE_OK
            denied.append(f"The table '{arg1}' is not available. Allowed tables: "
                          + ", ".join(sorted(allowed_tables)) + ".")
            return sqlite3.SQLITE_DENY
        if action == _SQLITE_FUNCTION:
            if (arg2 or "").lower() in _DENIED_FUNCTIONS:
                denied.append(f"The function '{arg2}' is not allowed.")
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        denied.append("Only reading data is allowed.")
        return sqlite3.SQLITE_DENY

    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.set_authorizer(authorizer)
        deadline = time.monotonic() + timeout
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)
        try:
            cur = conn.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            fetched = cur.fetchmany(max_rows + 1)
        except sqlite3.Warning:
            raise SQLGuardError("Only a single SELECT query is allowed.")
        except sqlite3.DatabaseError as e:
            if denied:
                raise SQLGuardError(denied[0])
            if "interrupted" in str(e).lower():
                raise SQLGuardError(f"The query took longer than {timeout:.0f} seconds.")
            raise SQLGuardError(f"SQL error: {e}")
    finally:
        conn.close()

    truncated = len(fetched) > max_rows
    rows = []
    for r in fetched[:max_rows]:
        rows.append({c: (round(v, 4) if isinstance(v, float) else v)
                     for c, v in zip(columns, r)})
    return {"columns": columns, "rows": rows, "truncated": truncated}
