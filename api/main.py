from fastapi import FastAPI

from api.routes import health, schema

app = FastAPI(title="Olist Query Studio")
app.include_router(health.router, prefix="/api")
app.include_router(schema.router, prefix="/api")
