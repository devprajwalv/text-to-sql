from fastapi import FastAPI

from api.routes import health

app = FastAPI(title="Olist Query Studio")
app.include_router(health.router, prefix="/api")
