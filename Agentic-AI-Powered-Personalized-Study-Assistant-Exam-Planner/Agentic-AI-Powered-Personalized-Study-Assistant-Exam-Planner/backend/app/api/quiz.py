"""Quiz API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.database import get_db
from backend.app.models.quiz import Quiz
from backend.app.schemas.quiz import (
    QuizGenerateRequest,
    QuizOut,
    QuizSubmitRequest,
    QuizResult,
)
from backend.app.services.quiz_engine import create_quiz, evaluate_quiz

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


@router.post("/generate", response_model=QuizOut, status_code=201)
async def generate_quiz(payload: QuizGenerateRequest, db: AsyncSession = Depends(get_db)):
    """Generate a new quiz for a topic."""
    import logging
    from backend.app.config import get_settings

    settings = get_settings()
    logger = logging.getLogger(__name__)

    try:
        return await create_quiz(db, payload)
    except Exception:
        logger.exception("Primary quiz generation failed; attempting rule-based fallback")
        original = settings.ai_provider
        try:
            settings.ai_provider = "rule_based"
            return await create_quiz(db, payload)
        except Exception:
            logger.exception("Rule-based fallback also failed for topic %s", payload.topic_id)
            from fastapi import HTTPException

            raise HTTPException(status_code=500, detail="Quiz generation failed")  # surface as 500 if all fail
        finally:
            settings.ai_provider = original


@router.post("/submit", response_model=QuizResult)
async def submit_quiz(payload: QuizSubmitRequest, db: AsyncSession = Depends(get_db)):
    """Submit answers and get evaluation results."""
    result = await evaluate_quiz(db, payload)
    return result


@router.get("/history/{user_id}", response_model=list[QuizOut])
async def quiz_history(user_id: str, db: AsyncSession = Depends(get_db)):
    """Get quiz history for a user."""
    q = (
        select(Quiz)
        .where(Quiz.user_id == user_id)
        .options(selectinload(Quiz.questions))
        .order_by(Quiz.created_at.desc())
    )
    result = await db.execute(q)
    return list(result.scalars().unique().all())
