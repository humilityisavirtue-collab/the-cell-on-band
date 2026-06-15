"""experiences.py — §9.8: fetch a published experience's metadata."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.errors import APIError, JOB_NOT_FOUND
from app.models import Experience

router = APIRouter(prefix="/experiences", tags=["experiences"])


@router.get("/{experience_id}")
async def get_experience(experience_id: str,
                         session: AsyncSession = Depends(get_session)):
    exp = await session.get(Experience, experience_id)
    if exp is None:
        raise APIError(JOB_NOT_FOUND, "No such experience.",
                       {"experience_id": experience_id})
    meta = exp.meta or {}
    return {
        "experience_id": exp.id, "job_id": exp.job_id,
        "public_url": exp.public_url,
        "metadata": {
            "chapter_title": meta.get("chapter_title"),
            "screen_count": meta.get("screen_count"),
            "faithfulness_score": meta.get("faithfulness_score"),
            "engagement_score": meta.get("engagement_score"),
        },
        "created_at": exp.created_at}
