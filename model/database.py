from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, event
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DATA = ROOT / "data"
ANALYTICS_DB = DATA / "olist.db"
LOG_DB = DATA / "studio.db"


@lru_cache
def engine(path: Path):
    db = create_engine(URL.create("sqlite", database=str(path)), poolclass=NullPool)

    @event.listens_for(db, "connect")
    def constraints(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    return db
