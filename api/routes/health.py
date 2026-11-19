import os

from fastapi import APIRouter
from agent.retriever import indexed_collection
from model.database import ANALYTICS_DB

router = APIRouter()


@router.get("/health")
def health():
    try:
        mode = "chroma" if indexed_collection() is not None else "full_schema"
    except Exception:
        mode = "unavailable"
    return {"status": "ok", "dataset_loaded": ANALYTICS_DB.is_file(),
            "key_configured": bool(os.getenv("OPENAI_API_KEY")),
            "retrieval_mode": mode}
