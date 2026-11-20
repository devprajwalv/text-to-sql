"""SQLite prepares and authorizes the exact statement before any review or execution."""
import math
import re
import sqlite3
import time
from contextlib import closing

from model.schema import analytics

ROW_LIMIT = 200
TIME_LIMIT = 3.0
SAFE_FUNCTIONS = frozenset("""
    abs avg cast ceil ceiling coalesce count cume_dist date datetime dense_rank first_value
    floor format glob group_concat ifnull iif instr julianday lag last_value lead length like
    lower ltrim max min nullif ntile percent_rank printf rank replace round row_number rtrim
    sign strftime substr substring sum time timediff total trim typeof unixepoch upper
""".split())


class Blocked(ValueError):
    pass


def read_query(path, sql, *, preview=False):
    if not re.match(r"^(select|with)\b", sql.strip(), re.I):
        raise Blocked("Questions run on a read-only connection. Use Propose a change for a data edit.")
    if not path.is_file():
        raise ValueError("Load the Olist data first with python -m data.seed.")
    reads_comments = False

    def authorize(action, table, column, db, source):
        nonlocal reads_comments
        allowed = action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE)
        if action == sqlite3.SQLITE_READ:
            # SQLite omits the database name on a column-free table read (COUNT(*)).
            allowed = table in analytics.tables and (db == "main" or (db is None and column == ""))
            reads_comments |= table == "dim_reviews" and column == "review_comment"
        if action == sqlite3.SQLITE_FUNCTION:
            allowed = column.lower() in SAFE_FUNCTIONS
        return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY

    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 131072)
        conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 20000)
        conn.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 80)
        conn.set_authorizer(authorize)
        deadline = time.monotonic() + TIME_LIMIT
        conn.set_progress_handler(lambda: time.monotonic() >= deadline, 1000)
        try:
            if preview:
                conn.execute("EXPLAIN " + sql)
                return reads_comments
            cursor = conn.execute(sql)
            rows = cursor.fetchmany(ROW_LIMIT + 1)
            results = [[display_value(value) for value in row] for row in rows[:ROW_LIMIT]]
            return {"columns": [c[0] for c in cursor.description], "results": results,
                    "truncated": len(rows) > ROW_LIMIT}
        except sqlite3.ProgrammingError as exc:
            raise Blocked("Submit one complete analytical statement at a time.") from exc
        except sqlite3.DatabaseError as exc:
            if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_AUTH:
                raise Blocked("The query requests an operation outside the read-only analytics catalog.") from exc
            if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_INTERRUPT:
                raise ValueError("The query reached its three-second time limit. Narrow your question.") from exc
            raise ValueError(f"SQLite could not run this query: {exc}") from exc


def display_value(value):
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value
