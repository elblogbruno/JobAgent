from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from packages.persistence.database import get_db
from packages.persistence.repositories import (
    CandidateAnswerRepository,
    ManualQuestionRepository,
)

router = APIRouter(prefix="/api/answers", tags=["Candidate Answers & Vault"])


class AnswerUpsertRequest(BaseModel):
    canonical_key: str
    answer: Any
    answer_type: str = "string"
    source: str = "user"
    confidence: float = 1.0
    raw_question: str = ""


class ManualAnswerRequest(BaseModel):
    answer: str


@router.get("", response_model=List[dict])
async def list_vault_answers(db: AsyncSession = Depends(get_db)):
    repo = CandidateAnswerRepository(db)
    answers = await repo.list_all()
    return [
        {
            "id": a.id,
            "canonical_key": a.question_canonical,
            "raw_question": a.question_raw,
            "answer": a.answer,
            "answer_type": a.answer_type,
            "source": a.source,
            "confidence": a.confidence,
            "usage_count": a.usage_count,
            "last_confirmed_at": a.last_confirmed_at.isoformat() if a.last_confirmed_at else None,
        }
        for a in answers
    ]


@router.post("")
async def upsert_vault_answer(req: AnswerUpsertRequest, db: AsyncSession = Depends(get_db)):
    repo = CandidateAnswerRepository(db)
    record = await repo.upsert_answer(
        canonical_key=req.canonical_key,
        answer=req.answer,
        answer_type=req.answer_type,
        source=req.source,
        confidence=req.confidence,
        raw_question=req.raw_question,
    )
    return {"status": "saved", "canonical_key": record.question_canonical}


@router.get("/pending-questions", response_model=List[dict])
async def list_pending_questions(db: AsyncSession = Depends(get_db)):
    repo = ManualQuestionRepository(db)
    questions = await repo.list_pending()
    return [
        {
            "id": q.id,
            "application_run_id": q.application_run_id,
            "question_text": q.question_text,
            "context": q.context,
            "status": q.status,
            "created_at": q.created_at.isoformat() if q.created_at else None,
        }
        for q in questions
    ]


@router.post("/pending-questions/{question_id}/answer")
async def answer_pending_question(
    question_id: str,
    req: ManualAnswerRequest,
    db: AsyncSession = Depends(get_db)
):
    repo = ManualQuestionRepository(db)
    item = await repo.answer(question_id, req.answer)
    if not item:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"status": "answered", "question_id": question_id}
