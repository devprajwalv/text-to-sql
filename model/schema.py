"""SQLAlchemy metadata also supplies the data dictionary shown to the analyst."""
from sqlalchemy import Column, Float, ForeignKey, Integer, JSON, MetaData, String, Table, Text

analytics = MetaData()
application = MetaData()

geography = Table(
    "dim_geography", analytics,
    Column("zip_prefix", String, primary_key=True, doc="Five-digit postal prefix, including leading zeroes."),
    Column("lat", Float, doc="Average observed latitude."),
    Column("lng", Float, doc="Average observed longitude."),
    comment="One centroid per postal prefix represented in the geolocation source.",
)
users = Table(
    "dim_users", analytics,
    Column("user_id", String, primary_key=True, doc="Order-specific customer ID from the source."),
    Column("unique_customer_id", String, nullable=False, doc="Buyer identifier shared across purchases."),
    Column("city", String, doc="Customer city at purchase."),
    Column("state", String, doc="Two-letter Brazilian state."),
    Column("zip_prefix", String, doc="Customer postal prefix. Left join dim_geography.zip_prefix."),
    comment="One customer address record per customer_id. Count distinct unique_customer_id for people.",
)
products = Table(
    "dim_products", analytics,
    Column("product_id", String, primary_key=True, doc="Catalog product identifier."),
    Column("category_name", String, doc="English category if translated, otherwise Portuguese. May be missing."),
    Column("photos_qty", Integer, doc="Number of listing photos."),
    comment="One catalog record per product.",
)
sellers = Table(
    "dim_sellers", analytics,
    Column("seller_id", String, primary_key=True, doc="Merchant identifier."),
    Column("city", String, doc="Registered seller city."),
    Column("state", String, doc="Registered seller state."),
    Column("zip_prefix", String, doc="Seller postal prefix. Left join dim_geography.zip_prefix."),
    comment="One record per merchant.",
)
orders = Table(
    "fact_orders", analytics,
    Column("order_id", String, primary_key=True, doc="Purchase identifier. Count distinct for order counts."),
    Column("item_seq", Integer, primary_key=True, doc="Order item sequence. Zero marks an order without items."),
    Column("user_id", ForeignKey("dim_users.user_id"), nullable=False),
    Column("product_id", ForeignKey("dim_products.product_id")),
    Column("seller_id", ForeignKey("dim_sellers.seller_id")),
    Column("created_at", String, doc="Local purchase timestamp, YYYY-MM-DD HH:MM:SS."),
    Column("order_status", String, doc="Order status such as delivered or canceled."),
    Column("price_cents", Integer, nullable=False, doc="Item price in BRL cents. Revenue in reais = SUM(price_cents)/100.0."),
    Column("freight_cents", Integer, nullable=False, doc="Item shipping charge in BRL cents, excluded from revenue."),
    comment="One row per purchased item, plus one zero-value row for each order without items. Count items with item_seq > 0.",
)
reviews = Table(
    "dim_reviews", analytics,
    Column("review_row", Integer, primary_key=True, doc="Unique source row number."),
    Column("review_id", String, doc="Source review identifier, which may repeat."),
    Column("order_id", String, index=True, doc="Links to fact_orders.order_id. Aggregate each side to order grain before joining."),
    Column("review_score", Integer, doc="Satisfaction rating from 1 to 5."),
    Column("review_comment", Text, doc="Optional review message in Portuguese."),
    comment="One submitted review record. An order can have multiple reviews.",
)
query_log = Table(
    "query_log", application,
    Column("request_id", String, primary_key=True),
    Column("created_at", String, nullable=False),
    Column("question", Text, nullable=False),
    Column("sql", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("message", String, nullable=False),
    Column("relevant_tables", JSON, nullable=False),
    Column("retrieval_mode", String, nullable=False),
    Column("latency_ms", Integer, nullable=False),
)

# Additive table so existing logs and pending SELECT reviews remain readable.
write_proposal = Table(
    "write_proposal", application,
    Column("request_id", ForeignKey("query_log.request_id"), primary_key=True),
    Column("operation", String, nullable=False),
    Column("target_table", String, nullable=False),
    Column("parameters", JSON, nullable=False),
    Column("snapshot", JSON, nullable=False),
    Column("expires_at", Integer, nullable=False),
)
