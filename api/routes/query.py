from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agent.sql_chain import ReviewConflict, ask, decide

router = APIRouter()


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=2000)
    review: bool = False


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    decision: Literal["approve", "cancel"]


class Answer(BaseModel):
    request_id: str
    question: str
    sql: str
    status: Literal["completed", "pending", "cancelled", "blocked", "error"]
    message: str
    columns: list[str]
    results: list[list[str | int | float | None]]
    truncated: bool
    relevant_tables: list[str]
    retrieval_mode: str
    latency_ms: int


@router.post("/query", response_model=Answer)
def query(body: Question):
    return ask(body.question, body.review)


@router.post("/approve", response_model=Answer)
def approve(body: Decision):
    try:
        return decide(str(body.request_id), body.decision == "approve")
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
