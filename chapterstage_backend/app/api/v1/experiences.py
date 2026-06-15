"""Experience metadata and reader progress endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_session
from app.models import User
from app.schemas import ReaderProgressResponse, ReaderProgressUpdate
from app.services import progress_service

router = APIRouter(prefix="/experiences", tags=["experiences"])


@router.get("/{experience_id}/progress", response_model=ReaderProgressResponse)
async def get_progress(
        experience_id: str,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)) -> ReaderProgressResponse:
    progress = await progress_service.get_progress(session, user.id, experience_id)
    return progress_service.to_response(experience_id, progress)


@router.put("/{experience_id}/progress", response_model=ReaderProgressResponse)
async def update_progress(
        experience_id: str,
        req: ReaderProgressUpdate,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)) -> ReaderProgressResponse:
    progress = await progress_service.upsert_progress(
        session, user.id, experience_id, req)
    return progress_service.to_response(experience_id, progress)
