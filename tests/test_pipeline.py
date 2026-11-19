import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from agent import hitl_guard, sql_chain
from data.seed import seed
from model.database import ANALYTICS_DB


def generated(client, monkeypatch, sql, review=False, question="Inspect orders"):
    def model(prompt):
        system, human = prompt.to_messages()
        assert "Worked examples" in system.content and "price_cents" in system.content
        assert human.content == question
        return AIMessage(content=sql)

    monkeypatch.setattr(sql_chain, "ChatOpenAI", lambda **kwargs: RunnableLambda(model))
    response = client.post("/api/query", json={"question": question, "review": review})
    response.raise_for_status()
    return response.json()


def decide(client, answer, decision):
    return client.post("/api/approve", json={"request_id": answer["request_id"], "decision": decision})


def test_seed_repeat_and_rollback(raw, database):
    assert seed(raw, database) == (3, 3, 1761)
    (raw / "olist_products_dataset.csv").write_text("wrong_header\ninvalid\n")
    with pytest.raises(ValueError, match="missing columns"):
        seed(raw, database)
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT COUNT(*), SUM(price_cents) FROM fact_orders").fetchone() == (4, 1761)
        assert db.execute("SELECT zip_prefix, lat FROM dim_geography").fetchone() == ("01001", -24)
        assert db.execute("SELECT COUNT(*) FROM dim_reviews").fetchone() == (2,)


def test_schema_and_empty_results(client, monkeypatch):
    schema = client.get("/api/schema").json()
    assert len(schema) == 6 and any(t["joins"] for t in schema)
    result = generated(client, monkeypatch, "SELECT product_id FROM dim_products WHERE 0")
    assert (result["columns"], result["results"], result["status"]) == (["product_id"], [], "completed")
    assert result["retrieval_mode"] == "full_schema" and len(result["relevant_tables"]) == 6


def test_count_without_column(client, monkeypatch):
    answer = generated(client, monkeypatch, "SELECT COUNT(*) FROM dim_products")
    assert answer["results"] == [[1]]


@pytest.mark.parametrize("sql", ["DELETE FROM fact_orders", "SELECT 1; SELECT 2",
                                  "WITH sample AS (SELECT 1) DELETE FROM fact_orders", "BLOCKED_WRITE"])
def test_blocked(client, monkeypatch, sql):
    answer = generated(client, monkeypatch, sql, review=True)
    assert answer["status"] == "blocked"
    assert decide(client, answer, "approve").status_code == 409


@pytest.mark.parametrize("decision, status", [("cancel", "cancelled"), ("approve", "completed")])
def test_review_comment_decision(client, monkeypatch, decision, status):
    answer = generated(client, monkeypatch, "SELECT review_comment FROM dim_reviews ORDER BY review_row")
    assert answer["status"] == "pending" and answer["results"] == []
    extra = {"request_id": answer["request_id"], "decision": decision, "sql": "SELECT 1"}
    assert client.post("/api/approve", json=extra).status_code == 422
    resolved = decide(client, answer, decision).json()
    assert resolved["status"] == status
    assert resolved["results"] == ([["Excellent"], [None]] if decision == "approve" else [])
    assert decide(client, answer, decision).status_code == 409
    with closing(sqlite3.connect(sql_chain.LOG_DB)) as db:
        assert db.execute("SELECT status FROM query_log").fetchone() == (status,)


def test_concurrent_decisions(client, monkeypatch):
    answer = generated(client, monkeypatch, "SELECT 1", review=True)
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: decide(client, answer, "approve"), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]


def test_row_cap_and_timeout(client, monkeypatch):
    recursive = "WITH RECURSIVE n(x) AS (SELECT 0 UNION ALL SELECT x+1 FROM n WHERE x<500)"
    answer = generated(client, monkeypatch, recursive + " SELECT x FROM n")
    assert answer["truncated"] and len(answer["results"]) == 200
    monkeypatch.setattr(hitl_guard, "TIME_LIMIT", 0)
    answer = generated(client, monkeypatch, recursive + " SELECT SUM(x) FROM n")
    assert answer["status"] == "error" and "time limit" in answer["message"]


def test_missing_key(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    assert client.post("/api/query", json={"question": "Orders?"}).json()["status"] == "error"


# Different SQL formulations for the model double and the independent database check.
MEASURES = [
    ("How many distinct orders were placed?",
     "SELECT COUNT(DISTINCT order_id) FROM fact_orders",
     "SELECT COUNT(*) FROM (SELECT order_id FROM fact_orders GROUP BY order_id)"),
    ("What was the total merchandise revenue in BRL?",
     "SELECT SUM(price_cents)/100.0 FROM fact_orders",
     "SELECT ROUND(SUM(per_order)/100.0, 2) FROM (SELECT SUM(price_cents) per_order FROM fact_orders GROUP BY order_id)"),
    ("Which customer state had the most distinct orders?",
     "SELECT u.state, COUNT(DISTINCT f.order_id) AS n FROM fact_orders f JOIN dim_users u USING(user_id) GROUP BY u.state ORDER BY n DESC, u.state LIMIT 1",
     """WITH purchases AS (SELECT DISTINCT order_id, user_id FROM fact_orders)
        SELECT state, COUNT(*) AS tally FROM dim_users JOIN purchases USING(user_id)
        GROUP BY state ORDER BY tally DESC, state LIMIT 1"""),
]


@pytest.mark.parametrize("question,sql,baseline", MEASURES)
@pytest.mark.parametrize("dataset", ["fixture", "full_olist"])
def test_analytical_answers(client, database, monkeypatch, question, sql, baseline, dataset):
    if dataset == "full_olist":
        if not ANALYTICS_DB.is_file():
            pytest.skip("Seed data/olist.db to include the full Olist checks")
        database = ANALYTICS_DB
    monkeypatch.setattr(sql_chain, "ANALYTICS_DB", database)
    answer = generated(client, monkeypatch, sql, question=question)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        expected = [list(row) for row in db.execute(baseline)]
    assert answer["status"] == "completed" and answer["results"] == expected
