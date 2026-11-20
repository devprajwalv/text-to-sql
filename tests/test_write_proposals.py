"""All mutations in this module use the isolated database and log fixtures."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from agent import sql_chain

QUESTION = "Change product p1's category to books."
UPDATE = "UPDATE dim_products SET category_name = :category WHERE product_id = :id"
PARAMS = {"category": "books", "id": "p1"}


def call(client, monkeypatch, question=QUESTION, sql=UPDATE, params=PARAMS, intent="change"):
    def reply(prompt):
        system, human = prompt.to_messages()
        assert human.content == question
        if intent == "change":
            assert "named :parameters" in system.content
            return AIMessage(content=json.dumps({"sql": sql, "parameters": params}))
        return AIMessage(content=sql)

    monkeypatch.setattr(sql_chain, "ChatOpenAI", lambda **_: RunnableLambda(reply))
    response = client.post("/api/query", json={"question": question, "intent": intent})
    response.raise_for_status()
    return response.json()


def decision(client, answer, choice):
    return client.post("/api/approve", json={"request_id": answer["request_id"], "decision": choice})


def products(db):
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as conn:
        return conn.execute("SELECT product_id, category_name, photos_qty FROM dim_products ORDER BY product_id").fetchall()


def execute_fixture(db, sql, params=()):
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute(sql, params)


def test_acceptance_cancel_then_approve_and_retry(client, database, monkeypatch):
    original = products(database)
    first = call(client, monkeypatch)
    assert first["status"] == "pending"
    assert first["change"]["before"][0]["category_name"] == "livros"
    assert first["change"]["after"][0]["category_name"] == "books"
    assert first["change"]["parameters"] == PARAMS and first["sql"] == UPDATE
    assert products(database) == original

    assert decision(client, first, "cancel").json()["status"] == "cancelled"
    assert decision(client, first, "approve").status_code == 409
    assert products(database) == original
    second = call(client, monkeypatch)
    assert second["request_id"] != first["request_id"] and products(database) == original
    assert decision(client, second, "approve").json()["status"] == "completed"
    read = call(client, monkeypatch, "What is the category of p1?",
                "SELECT category_name FROM dim_products WHERE product_id='p1'", intent="read")
    assert read["status"] == "completed" and read["results"] == [["books"]]
    assert decision(client, second, "approve").status_code == 409
    assert products(database) == [("p1", "books", 2)]


def test_insert_and_delete(client, database, monkeypatch):
    original = products(database)
    insert = call(client, monkeypatch, "Add a new product p2 in category owner's books.",
                  "INSERT INTO dim_products (product_id, category_name) VALUES (:id, :category)",
                  {"id": "p2", "category": "owner's books"})
    assert insert["status"] == "pending" and insert["change"]["before"] == []
    assert insert["change"]["after"] == [{"product_id": "p2", "category_name": "owner's books", "photos_qty": None}]
    assert insert["change"]["affected_count"] == 1 and products(database) == original
    assert "owner's books" not in insert["sql"]
    assert decision(client, insert, "approve").json()["status"] == "completed"
    added = [*original, ("p2", "owner's books", None)]
    assert products(database) == added
    delete = call(client, monkeypatch, "Delete product p2.", "DELETE FROM dim_products WHERE product_id=:id", {"id": "p2"})
    assert delete["change"]["after"] == [] and delete["change"]["before"] == insert["change"]["after"]
    assert products(database) == added
    assert decision(client, delete, "approve").json()["status"] == "completed"
    assert products(database) == original


def test_concurrent_approvals(client, database, monkeypatch):
    original = products(database)
    answer = call(client, monkeypatch)
    assert products(database) == original
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: decision(client, answer, "approve"), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert [r.json()["status"] for r in responses if r.status_code == 200] == ["completed"]
    assert products(database) == [("p1", "books", 2)]


def test_decision_cannot_replace_bindings(client, database, monkeypatch):
    original = products(database)
    proposal = call(client, monkeypatch)
    forged = {"request_id": proposal["request_id"], "decision": "approve", "parameters": {"category": "other"}}
    assert client.post("/api/approve", json=forged).status_code == 422
    assert products(database) == original
    assert decision(client, proposal, "approve").json()["status"] == "completed"
    assert products(database) == [("p1", "books", 2)]


def test_stale_insert_keeps_intervening_row(client, database, monkeypatch):
    original = products(database)
    answer = call(client, monkeypatch, "Add product p2.", "INSERT INTO dim_products (product_id) VALUES (:id)",
                  {"id": "p2"})
    assert answer["status"] == "pending" and products(database) == original
    execute_fixture(database, "INSERT INTO dim_products VALUES ('p2', 'other', 7)")
    assert decision(client, answer, "approve").json()["status"] == "error"
    assert products(database) == [*original, ("p2", "other", 7)]


@pytest.mark.parametrize("intervening", [
    "UPDATE dim_products SET photos_qty=9 WHERE product_id='p1'",
    "INSERT INTO dim_products VALUES ('p2','livros',1)",
    "UPDATE dim_products SET category_name='elsewhere' WHERE product_id='p1'",
])
def test_stale_update(client, database, monkeypatch, intervening):
    original = products(database)
    answer = call(client, monkeypatch, sql="UPDATE dim_products SET photos_qty=:n WHERE category_name=:c",
                  params={"n": 4, "c": "livros"})
    assert products(database) == original
    execute_fixture(database, intervening)
    latest = products(database)
    result = decision(client, answer, "approve").json()
    assert result["status"] == "error" and "fresh proposal" in result["message"]
    assert decision(client, answer, "approve").status_code == 409 and products(database) == latest


def test_expired(client, database, monkeypatch):
    original = products(database)
    answer = call(client, monkeypatch)
    assert products(database) == original
    execute_fixture(sql_chain.LOG_DB, "UPDATE write_proposal SET expires_at=0 WHERE request_id=?", (answer["request_id"],))
    result = decision(client, answer, "approve").json()
    assert result["status"] == "error" and "expired" in result["message"]
    assert decision(client, answer, "approve").status_code == 409 and products(database) == original


@pytest.mark.parametrize("question,sql,params", [
    (QUESTION, "UPDATE dim_products SET category_name=:category", {"category": "books"}),
    ("Delete product p1.", "DELETE FROM dim_products", {}),
    (QUESTION, UPDATE + "; SELECT 1", PARAMS),
    (QUESTION, "UPDATE query_log SET message=:category WHERE request_id=:id", PARAMS),
    (QUESTION, "UPDATE write_proposal SET parameters=:category WHERE request_id=:id", PARAMS),
    (QUESTION, "UPDATE fact_orders SET order_status=:category WHERE order_id=:id", PARAMS),
    (QUESTION, "UPDATE dim_sellers SET city=:category WHERE seller_id=:id", PARAMS),
    (QUESTION, "UPDATE dim_products SET product_id=:category WHERE product_id=:id", PARAMS),
    (QUESTION, "UPDATE dim_products SET photos_qty=:category WHERE product_id=:id", PARAMS),
    (QUESTION, "UPDATE dim_products SET photos_qty=:n WHERE product_id=:id", {"n": 2**53 + 1, "id": "p1"}),
    (QUESTION, "DELETE FROM dim_products WHERE product_id=:id", {"id": "p1"}),
    (QUESTION, "UPDATE dim_products SET category_name='books' WHERE product_id='p1'", {}),
    ("How many products are in category books?", UPDATE, PARAMS),
    ("Add up all item prices.", UPDATE, PARAMS),
])
def test_rejected_statements(client, database, monkeypatch, question, sql, params):
    original = products(database)
    answer = call(client, monkeypatch, question, sql, params)
    assert answer["status"] == "blocked" and answer["change"] is None
    assert decision(client, answer, "approve").status_code == 409
    assert products(database) == original


def test_oversized_and_boundary(client, database, monkeypatch):
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executemany("INSERT INTO dim_products VALUES (?, 'batch', 1)", [(f"b{i}",) for i in range(11)])
    original = products(database)
    answer = call(client, monkeypatch, sql="UPDATE dim_products SET photos_qty=:n WHERE category_name=:name",
                  params={"n": 2, "name": "batch"})
    assert answer["status"] == "blocked" and products(database) == original
    placeholders = ", ".join(f"(:id{i})" for i in range(11))
    insert = call(client, monkeypatch, "Add new products.", f"INSERT INTO dim_products (product_id) VALUES {placeholders}",
                  {f"id{i}": f"new{i}" for i in range(11)})
    assert insert["status"] == "blocked" and products(database) == original
    execute_fixture(database, "DELETE FROM dim_products WHERE product_id='b10'")
    before_ten = products(database)
    delete = call(client, monkeypatch, "Delete products in category batch.",
                  "DELETE FROM dim_products WHERE category_name=:name", {"name": "batch"})
    assert delete["change"]["affected_count"] == 10 and products(database) == before_ten
    assert decision(client, delete, "approve").json()["status"] == "completed"
    assert products(database) == [("p1", "livros", 2)]


def test_failed_constraint_consumes_proposal(client, database, monkeypatch):
    original = products(database)
    answer = call(client, monkeypatch, "Remove product p1.", "DELETE FROM dim_products WHERE product_id=:id", {"id": "p1"})
    assert answer["status"] == "pending" and products(database) == original
    result = decision(client, answer, "approve").json()
    assert result["status"] == "error" and "FOREIGN KEY" in result["message"]
    assert decision(client, answer, "approve").status_code == 409 and products(database) == original


def test_failed_audit_rolls_back_business_change(client, database, monkeypatch):
    original = products(database)
    answer = call(client, monkeypatch)
    execute_fixture(sql_chain.LOG_DB, """CREATE TRIGGER fail_audit BEFORE UPDATE ON query_log
                                        BEGIN SELECT RAISE(ABORT, 'test audit failure'); END""")
    assert decision(client, answer, "approve").status_code == 503
    assert products(database) == original
    execute_fixture(sql_chain.LOG_DB, "DROP TRIGGER fail_audit")
    assert decision(client, answer, "approve").json()["status"] == "completed"
    assert products(database) == [("p1", "books", 2)]
