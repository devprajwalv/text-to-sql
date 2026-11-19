from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import health, query, schema
from model.database import LOG_DB, engine
from model.schema import application


@asynccontextmanager
async def lifespan(app):
    application.create_all(engine(LOG_DB))
    yield


app = FastAPI(title="Olist Query Studio", lifespan=lifespan)
app.include_router(health.router, prefix="/api")
app.include_router(schema.router, prefix="/api")
app.include_router(query.router, prefix="/api")
