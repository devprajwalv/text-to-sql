import os
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from agent.hitl_guard import Blocked, read_query
from agent.retriever import retrieve
from agent.semantic_layer import document
from model.database import ANALYTICS_DB, LOG_DB, engine
from model.schema import query_log

INSTRUCTIONS = """Write a single SQLite SELECT for the analyst's question. Return plain SQL only.
For a request to change data or schema, return the single token BLOCKED_WRITE.
Use the catalog below. Give result columns meaningful names. Counts of orders include orders without
items. Merchandise revenue includes all statuses unless a status is specified. Convert cents to BRL.
Use stable tie breakers in rankings and group at the appropriate grain before joining reviews.

Catalog
{schema}

Worked examples
{examples}"""


def generate(question, tables):
    examples = yaml.safe_load(Path(__file__).with_name("few_shot_examples.yaml").read_text(encoding="utf8"))
    prompt = ChatPromptTemplate.from_messages([("system", INSTRUCTIONS), ("human", "{question}")])
    model = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-6.2-sol"), use_responses_api=True,
                       timeout=60, max_retries=1)
    chain = prompt | model | StrOutputParser()
    answer = chain.invoke({"question": question, "schema": "\n\n".join(map(document, tables)),
                           "examples": "\n".join(f"{e['question']}\n{e['sql']}" for e in examples)})
    return answer.strip().removeprefix("```sql").removeprefix("```").removesuffix("```").strip()


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


def ask(question, review):
    start = time.monotonic()
    record = dict(request_id=str(uuid4()), question=question, created_at=datetime.now(UTC).isoformat(),
                  sql="", status="error", message="", relevant_tables=[], retrieval_mode="unavailable")
    result = empty_result()
    try:
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("Add OPENAI_API_KEY to the root .env and restart FastAPI.")
        if not ANALYTICS_DB.is_file():
            raise ValueError("Load the Olist data with python -m data.seed.")
        try:
            mode, tables = retrieve(question)
            record.update(retrieval_mode=mode, relevant_tables=[t["table_name"] for t in tables])
            sql = generate(question, tables)
        except Exception as exc:
            raise ValueError("Model or schema retrieval failed. Check the backend key, model access, network and index.") from exc
        if sql == "BLOCKED_WRITE":
            raise Blocked("Changes to data and schema are blocked in this read-only workspace.")
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
    record["latency_ms"] = elapsed(start)
    with engine(LOG_DB).begin() as conn:
        conn.execute(query_log.insert().values(**record))
    return {**record, **result}


class ReviewConflict(ValueError):
    pass


def decide(request_id, approve):
    start = time.monotonic()
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
