"""Small synthetic orders for offline tests; use the same CSV headers as Olist."""
import pytest
from fastapi.testclient import TestClient

from agent import retriever, sql_chain
from api import main
from data.seed import seed

CSV = {
    "customers": """customer_id,customer_unique_id,customer_zip_code_prefix,customer_city,customer_state
c1,buyer1,01001,sao paulo,SP
c2,buyer1,01002,santos,SP
c3,buyer2,20000,rio,RJ""",
    "products": """product_id,product_category_name,product_name_lenght,product_description_lenght,product_photos_qty,product_weight_g,product_length_cm,product_height_cm,product_width_cm
p1,livros,3,3,2,100,1,1,1""",
    "sellers": """seller_id,seller_zip_code_prefix,seller_city,seller_state
s1,01001,sao paulo,SP""",
    "geolocation": """geolocation_zip_code_prefix,geolocation_lat,geolocation_lng,geolocation_city,geolocation_state
01001,-23,-46,sao paulo,SP
01001,-25,-48,sao paulo,SP""",
    "orders": """order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at,order_delivered_carrier_date,order_delivered_customer_date,order_estimated_delivery_date
o1,c1,delivered,2018-01-01 10:00:00,,,,
o2,c2,delivered,2018-01-02 10:00:00,,,,
o3,c3,canceled,2018-01-03 10:00:00,,,,""",
    "order_items": """order_id,order_item_id,product_id,seller_id,shipping_limit_date,price,freight_value
o1,1,p1,s1,2018-01-01,10.25,1.50
o1,2,p1,s1,2018-01-01,2.35,1.50
o2,1,p1,s1,2018-01-02,5.01,2.00""",
    "order_reviews": """review_id,order_id,review_score,review_comment_title,review_comment_message,review_creation_date,review_answer_timestamp
r1,o1,5,,Excellent,2018-01-10,2018-01-11
r1,o2,4,,,2018-01-11,2018-01-12""",
}


@pytest.fixture
def raw(tmp_path):
    folder = tmp_path / "raw"
    folder.mkdir()
    for name, content in CSV.items():
        (folder / f"olist_{name}_dataset.csv").write_text(content, encoding="utf8")
    return folder


@pytest.fixture
def database(raw, tmp_path):
    path = tmp_path / "fixture.db"
    assert seed(raw, path) == (3, 3, 1761)
    return path


@pytest.fixture
def client(database, tmp_path, monkeypatch):
    log = tmp_path / "log.db"
    monkeypatch.setattr(main, "LOG_DB", log)
    monkeypatch.setattr(sql_chain, "LOG_DB", log)
    monkeypatch.setattr(sql_chain, "ANALYTICS_DB", database)
    monkeypatch.setattr(retriever, "INDEX", tmp_path / "index")
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    with TestClient(main.app) as api:
        yield api
