"""Persistence helpers for account-backed reading progress."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReaderProgress, _now
from app.schemas import ReaderProgressResponse, ReaderProgressUpdate


async def get_progress(
        session: AsyncSession, user_id: str,
        experience_id: str) -> ReaderProgress | None:
    return (await session.execute(
        select(ReaderProgress).where(
            ReaderProgress.user_id == user_id,
            ReaderProgress.experience_id == experience_id,
        ))).scalar_one_or_none()


async def upsert_progress(
        session: AsyncSession, user_id: str, experience_id: str,
        req: ReaderProgressUpdate) -> ReaderProgress:
    row = await get_progress(session, user_id, experience_id)
    if row is None:
        row = ReaderProgress(user_id=user_id, experience_id=experience_id)
    row.current_screen_id = req.current_screen_id
    row.completed_screen_ids = list(dict.fromkeys(req.completed_screen_ids))
    row.last_checkpoint = req.last_checkpoint
    row.interaction_state = req.interaction_state
    row.updated_at = _now()
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


def to_response(
        experience_id: str,
        progress: ReaderProgress | None) -> ReaderProgressResponse:
    if progress is None:
        return ReaderProgressResponse(experience_id=experience_id)
    return ReaderProgressResponse(
        experience_id=experience_id,
        current_screen_id=progress.current_screen_id,
        completed_screen_ids=progress.completed_screen_ids or [],
        last_checkpoint=progress.last_checkpoint,
        interaction_state=progress.interaction_state or {},
        updated_at=progress.updated_at,
    )
