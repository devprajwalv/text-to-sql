from fastapi import APIRouter

from agent.semantic_layer import catalog

router = APIRouter()


@router.get("/schema")
def schema():
    return catalog()
