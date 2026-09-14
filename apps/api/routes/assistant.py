"""The form assistant: answering a field the candidate is stuck on.

Grounded in their CV, their profile and the posting on screen. It drafts text
they will paste into a real application, so it refuses to invent rather than
filling a gap with something plausible.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.security import require_extension_token
from packages.assistant.application_assistant import ApplicationAssistant, ChatTurn
from packages.persistence.database import get_db

router = APIRouter(prefix="/api/assistant", tags=["Assistant"])

MAX_QUESTION_CHARS = 4000
MAX_CONTEXT_CHARS = 4000


def _history(raw: Any) -> List[ChatTurn]:
    turns: List[ChatTurn] = []
    if not isinstance(raw, list):
        return turns
    for item in raw[-12:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role in ("user", "assistant") and content:
            turns.append(ChatTurn(role=role, content=content[:2000]))
    return turns


@router.post("/chat")
async def ask_assistant(
    payload: Dict[str, Any] = Body(...),
    token=Depends(require_extension_token),
    db: AsyncSession = Depends(get_db),
):
    """Drafts an answer for one form field."""
    question = str(payload.get("question") or payload.get("message") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    assistant = ApplicationAssistant(db)
    answer = await assistant.answer(
        question=question[:MAX_QUESTION_CHARS],
        job_id=(payload.get("jobId") or payload.get("job_id") or None),
        page_context=str(payload.get("pageContext") or "")[:MAX_CONTEXT_CHARS],
        history=_history(payload.get("history")),
    )
    return answer.to_api_dict()


@router.post("/answers")
async def remember_answer(
    payload: Dict[str, Any] = Body(...),
    token=Depends(require_extension_token),
    db: AsyncSession = Depends(get_db),
):
    """Stores a confirmed answer so the same field is instant next time.

    Only questions the vault recognises are stored, because an arbitrary form
    field has no stable identity to recall it by.
    """
    question = str(payload.get("question") or "").strip()
    answer = str(payload.get("answer") or "").strip()
    if not question or not answer:
        raise HTTPException(status_code=400, detail="question and answer are required")

    key = await ApplicationAssistant(db).save_answer(question, answer)
    if key is None:
        return {
            "status": "skipped",
            "message": "That field is not one the answer vault recognises, so it was not stored.",
        }
    return {"status": "success", "canonicalKey": key}
