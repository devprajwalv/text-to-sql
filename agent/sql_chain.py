import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml
from sqlalchemy import select
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from agent.hitl_guard import Blocked, read_query
from agent.retriever import retrieve
from agent.semantic_layer import catalog, document
from agent.write_execution import ReviewConflict, ReviewUnavailable, approve_write
from agent.write_proposals import MAX_ROWS, TTL_SECONDS, parse_model_reply, preview_readonly, requested_change
from model.database import ANALYTICS_DB, LOG_DB, engine
from model.schema import query_log, write_proposal

INSTRUCTIONS = """Write a single SQLite SELECT for the analyst's question. Return plain SQL only.
For a request to change data or schema, return the single token BLOCKED_WRITE.
Use the catalog below. Give result columns meaningful names. Counts of orders include orders without
items. Merchandise revenue includes all statuses unless a status is specified. Convert cents to BRL.
Use stable tie breakers in rankings and group at the appropriate grain before joining reviews.

Catalog
{schema}

Worked examples
{examples}"""


CHANGE_INSTRUCTIONS = """Prepare a single {operation} proposal only for an explicit request to modify data.
If the request is analytical, hypothetical, ambiguous, lacks a required value or key, or asks for
anything else, return BLOCKED_WRITE. Never invent a value, key, or filter.
Return a JSON object with keys sql and parameters. Use bare identifiers and named :parameters for
every value. Parameter keys omit the colon. Strings (including IDs), integers, and null retain their
JSON types. No SQL literals, expressions, functions, joins, or subqueries.
INSERT uses an explicit column list (including the key) and VALUES. UPDATE sets non-key columns.
UPDATE and DELETE require WHERE with column = :parameter comparisons joined by AND. Limit {max_rows} rows.
Allowed tables, columns, and types:
{schema}
Example format: {example}"""


def generate(question, tables, operation=None):
    prompt = ChatPromptTemplate.from_messages([("system", CHANGE_INSTRUCTIONS if operation else INSTRUCTIONS),
                                               ("human", "{question}")])
    model = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-6.2-sol"), use_responses_api=True,
                       timeout=60, max_retries=1)
    chain = prompt | model | StrOutputParser()
    context = {"question": question, "schema": "\n\n".join(map(document, tables))}
    if operation:
        context.update(operation=operation, max_rows=MAX_ROWS,
                       example='{"sql":"UPDATE dim_products SET photos_qty = :qty WHERE product_id = :id",'
                               '"parameters":{"qty":2,"id":"p1"}}')
    else:
        examples = yaml.safe_load(Path(__file__).with_name("few_shot_examples.yaml").read_text(encoding="utf8"))
        context["examples"] = "\n".join(f"{e['question']}\n{e['sql']}" for e in examples)
    answer = chain.invoke(context)
    return answer.strip().removeprefix("```sql").removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def elapsed(start):
    return round((time.monotonic() - start) * 1000)


def empty_result():
    return {"columns": [], "results": [], "truncated": False}


def execute(record):
    try:
        result = read_query(ANALYTICS_DB, record["sql"])
        record.update(status="completed", message="")
        return result
    except Blocked as exc:
        record.update(status="blocked", message=str(exc))
    except ValueError as exc:
        record.update(status="error", message=str(exc))
    return empty_result()


def ask(question, review, intent="read"):
    start = time.monotonic()
    record = dict(request_id=str(uuid4()), question=question, created_at=datetime.now(UTC).isoformat(),
                  sql="", status="error", message="", relevant_tables=[], retrieval_mode="unavailable")
    result = empty_result()
    proposal = None
    try:
        operation, target = requested_change(question) if intent == "change" else (None, None)
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("Add OPENAI_API_KEY to the root .env and restart FastAPI.")
        if not ANALYTICS_DB.is_file():
            raise ValueError("Load the Olist data with python -m data.seed.")
        try:
            if operation:
                mode, tables = "write_allowlist", [t for t in catalog() if t["table_name"] == target]
            else:
                mode, tables = retrieve(question)
            record.update(retrieval_mode=mode, relevant_tables=[t["table_name"] for t in tables])
            sql = generate(question, tables, operation) if operation else generate(question, tables)
        except Exception as exc:
            raise ValueError("Model or schema retrieval failed. Check the backend key, model access, network and index.") from exc
        if sql == "BLOCKED_WRITE":
            raise Blocked("A supported change needs an explicit action, values, and target in Propose a change.")
        if operation:
            plan = parse_model_reply(sql, operation)
            if plan.table != target:
                raise Blocked("The generated change targets a different table from the request.")
            record["sql"] = plan.sql
            snapshot = preview_readonly(ANALYTICS_DB, plan)
            expiry = int(time.time()) + TTL_SECONDS
            proposal = dict(request_id=record["request_id"], operation=plan.operation, target_table=plan.table,
                            parameters=plan.parameters, snapshot=snapshot, expires_at=expiry)
            result["change"] = dict(operation=plan.operation, target_table=plan.table, parameters=plan.parameters,
                                    expires_at=expiry, **snapshot)
            record.update(status="pending", message="Review the proposed rows before applying this change.")
        else:
            record["sql"] = sql
            reads_comments = read_query(ANALYTICS_DB, sql, preview=True)
            if reads_comments or review:
                reason = "This query reads customer review text." if reads_comments else "You requested a SQL review."
                record.update(status="pending", message=reason)
            else:
                result = execute(record)
    except Blocked as exc:
        record.update(status="blocked", message=str(exc))
    except ValueError as exc:
        record["message"] = str(exc)
    except sqlite3.DatabaseError as exc:
        record["message"] = f"SQLite could not preview this change: {exc}"
    record["latency_ms"] = elapsed(start)
    with engine(LOG_DB).begin() as conn:
        conn.execute(query_log.insert().values(**record))
        if proposal:
            conn.execute(write_proposal.insert().values(**proposal))
    return {**record, **result}


def decide(request_id, approve):
    start = time.monotonic()
    if approve:
        with engine(LOG_DB).connect() as conn:
            is_write = conn.scalar(select(write_proposal.c.request_id).where(write_proposal.c.request_id == request_id))
        if is_write:
            try:
                return {**approve_write(ANALYTICS_DB, LOG_DB, request_id), **empty_result()}
            except sqlite3.DatabaseError as exc:
                raise ReviewUnavailable("SQLite could not finish approval. Retry your decision.") from exc
    with engine(LOG_DB).begin() as conn:
        # Claim and finish in one transaction. A failed process rolls back the claim.
        claim = query_log.update().where(query_log.c.request_id == request_id,
                                         query_log.c.status == "pending").values(status="reviewing")
        row = conn.execute(claim.returning(*query_log.c)).mappings().one_or_none()
        if row is None:
            raise ReviewConflict("This request is unknown or has already been resolved.")
        record = dict(row)
        if approve:
            result = execute(record)
        else:
            result = empty_result()
            record.update(status="cancelled", message="Query cancelled before execution.")
        record["latency_ms"] += elapsed(start)
        conn.execute(query_log.update().where(query_log.c.request_id == request_id).values(
            status=record["status"], message=record["message"], latency_ms=record["latency_ms"]))
    return {**record, **result}
