"""Load the Olist CSVs into a single atomic analytical snapshot."""
import csv
from itertools import batched
from pathlib import Path

from model.database import ANALYTICS_DB, DATA, LOG_DB, engine
from model.schema import analytics, application

# Only these named source columns are staged. Extra CSV columns are welcome.
SOURCES = {
    "customers": "customer_id customer_unique_id customer_city customer_state customer_zip_code_prefix",
    "products": "product_id product_category_name product_photos_qty",
    "sellers": "seller_id seller_city seller_state seller_zip_code_prefix",
    "geolocation": "geolocation_zip_code_prefix geolocation_lat geolocation_lng",
    "orders": "order_id customer_id order_purchase_timestamp order_status",
    "order_items": "order_id order_item_id product_id seller_id price freight_value",
    "order_reviews": "review_id order_id review_score review_comment_message",
}
TRANSLATION = "product_category_name_translation.csv"


def stage(conn, name, path, columns):
    fields = columns.split()
    conn.exec_driver_sql(f"CREATE TEMP TABLE src_{name} ({', '.join(fields)})")
    if path is None:
        return
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(fields).difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name} is missing columns: {', '.join(sorted(missing))}")
        statement = f"INSERT INTO src_{name} VALUES ({', '.join('?' for _ in fields)})"
        rows = (tuple(row[field] or None for field in fields) for row in reader)
        for chunk in batched(rows, 5000):
            conn.exec_driver_sql(statement, list(chunk))


def seed(raw: Path = DATA / "raw", destination: Path = ANALYTICS_DB):
    paths = {key: raw / f"olist_{key}_dataset.csv" for key in SOURCES}
    missing = [path.name for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Place these Olist CSVs in {raw}: {', '.join(missing)}")
    with engine(destination).begin() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        analytics.create_all(conn)
        for table in reversed(analytics.sorted_tables):
            conn.execute(table.delete())
        for key, path in paths.items():
            stage(conn, key, path, SOURCES[key])
        translation = raw / TRANSLATION
        stage(conn, "translations", translation if translation.is_file() else None,
              "product_category_name product_category_name_english")

        for statement in LOAD_STATEMENTS:
            conn.exec_driver_sql(statement)
        return conn.exec_driver_sql("""
            SELECT COUNT(DISTINCT order_id), SUM(item_seq > 0), SUM(price_cents)
            FROM fact_orders
        """).one()


LOAD_STATEMENTS = [
    """INSERT INTO dim_users
       SELECT customer_id, customer_unique_id, customer_city, customer_state,
              customer_zip_code_prefix FROM src_customers""",
    """INSERT INTO dim_geography
       SELECT geolocation_zip_code_prefix, AVG(geolocation_lat), AVG(geolocation_lng)
       FROM src_geolocation GROUP BY geolocation_zip_code_prefix""",
    """INSERT INTO dim_products
       SELECT p.product_id, COALESCE(t.product_category_name_english, p.product_category_name),
              p.product_photos_qty FROM src_products p
       LEFT JOIN src_translations t USING (product_category_name)""",
    """INSERT INTO dim_sellers
       SELECT seller_id, seller_city, seller_state, seller_zip_code_prefix FROM src_sellers""",
    """INSERT INTO fact_orders
       SELECT o.order_id, COALESCE(i.order_item_id, 0), o.customer_id, i.product_id, i.seller_id,
              o.order_purchase_timestamp, o.order_status, COALESCE(ROUND(i.price * 100), 0),
              COALESCE(ROUND(i.freight_value * 100), 0)
       FROM src_orders o LEFT JOIN src_order_items i USING (order_id)""",
    """INSERT INTO dim_reviews
       SELECT rowid, review_id, order_id, review_score, review_comment_message FROM src_order_reviews""",
]


if __name__ == "__main__":
    orders, items, cents = seed()
    application.create_all(engine(LOG_DB))
    print(f"{orders:,} orders | {items:,} items | BRL {cents / 100:,.2f} merchandise revenue")
