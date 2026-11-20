"""Commit a reviewed business change and its audit outcome in one SQLite transaction."""
import json
import sqlite3
import time
from contextlib import closing

from agent.write_proposals import parse, preview, rows_by_key


class ReviewConflict(ValueError):
    pass


class ReviewUnavailable(ValueError):
    pass


def apply(conn, plan, snapshot):
    try:
        current = preview(conn, plan)
    except ValueError:
        current = None
    if current != snapshot:
        raise ValueError("The matching rows changed after preview. Submit a fresh proposal.")

    # Reject trigger/cascade side effects outside the exact approved mutation.
    mutations = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
    expected = getattr(sqlite3, "SQLITE_" + plan.operation)

    def authorize(action, table, column, database, source):
        if source or (action in mutations and (action, database, table) != (expected, "main", plan.table)):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    prior_changes = conn.total_changes
    conn.set_authorizer(authorize)
    try:
        count = conn.execute(plan.sql, plan.parameters).rowcount
    finally:
        conn.set_authorizer(None)
    if count != snapshot["affected_count"] or conn.total_changes - prior_changes != count:
        raise ValueError("Affected-row count differed from the preview. The change was rolled back.")
    keys = [r[plan.key] for r in snapshot["before"] or snapshot["after"]]
    if rows_by_key(conn, plan, keys) != snapshot["after"]:
        raise ValueError("Stored values differed from the preview. The change was rolled back.")


def approve_write(analytics_path, log_path, request_id):
    start = time.monotonic()
    # SQLite's super-journal covers both on-disk files in rollback-journal mode.
    with closing(sqlite3.connect(analytics_path.as_uri() + "?mode=rw", uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("ATTACH DATABASE ? AS studio", (log_path.as_uri() + "?mode=rw",))
        for schema in ("main", "studio"):
            conn.execute(f"PRAGMA {schema}.synchronous=FULL")
        conn.execute("BEGIN IMMEDIATE")
        for schema in ("main", "studio"):
            if conn.execute(f"PRAGMA {schema}.journal_mode").fetchone()[0] not in {"delete", "truncate", "persist"}:
                raise ReviewUnavailable("Both databases need rollback-journal mode for an atomic approval.")
        row = conn.execute("""
            SELECT q.*, p.operation, p.target_table, p.parameters, p.snapshot, p.expires_at
            FROM studio.query_log q JOIN studio.write_proposal p USING(request_id)
            WHERE q.request_id = ? AND q.status = 'pending'
        """, (request_id,)).fetchone()
        if row is None:
            raise ReviewConflict("This proposal has already been resolved.")
        record = dict(row)
        params = json.loads(record.pop("parameters"))
        snapshot = json.loads(record.pop("snapshot"))
        operation = record.pop("operation")
        table = record.pop("target_table")
        expiry = record.pop("expires_at")
        record["relevant_tables"] = json.loads(record["relevant_tables"])
        if time.time() >= expiry:
            status, message = "error", "This proposal expired. Submit a fresh proposal."
        else:
            conn.execute("SAVEPOINT change_rows")
            try:
                plan = parse(record["sql"], params, operation)
                if plan.table != table or plan.sql != record["sql"]:
                    raise ValueError("Stored proposal is inconsistent. Submit a fresh proposal.")
                apply(conn, plan, snapshot)
                status, message = "completed", f"{operation} applied to {snapshot['affected_count']} row(s) in {table}."
            except (ValueError, sqlite3.DatabaseError) as exc:
                conn.execute("ROLLBACK TO change_rows")
                status = "error"
                message = str(exc) if isinstance(exc, ValueError) else f"SQLite rejected the change: {exc}. No rows changed."
            conn.execute("RELEASE change_rows")
        record.update(status=status, message=message,
                      latency_ms=record["latency_ms"] + round((time.monotonic() - start) * 1000))
        conn.execute("""UPDATE studio.query_log SET status=:status, message=:message, latency_ms=:latency_ms
                        WHERE request_id=:request_id""",
                     {k: record[k] for k in ("status", "message", "latency_ms", "request_id")})
        conn.commit()
    return {**record, "change": {"operation": operation, "target_table": table, "parameters": params,
                                 "expires_at": expiry, **snapshot}}
