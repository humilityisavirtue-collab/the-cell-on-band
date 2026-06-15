"""Experience metadata and reader progress endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.errors import APIError, EXPERIENCE_NOT_FOUND
from app.models import Experience
from app.schemas import (ExperienceResponse, ReaderProgressResponse,
                         ReaderProgressUpdate)
from app.services import progress_service

router = APIRouter(prefix="/experiences", tags=["experiences"])


@router.get("/{experience_id}", response_model=ExperienceResponse)
async def get_experience(
        experience_id: str,
        session: AsyncSession = Depends(get_session)) -> ExperienceResponse:
    experience = await session.get(Experience, experience_id)
    if experience is None:
        raise APIError(EXPERIENCE_NOT_FOUND, "No such experience.",
                       {"experience_id": experience_id})
    return ExperienceResponse(
        experience_id=experience.id,
        job_id=experience.job_id,
        public_url=experience.public_url,
        metadata=experience.meta,
        created_at=experience.created_at,
    )


@router.get("/{experience_id}/progress", response_model=ReaderProgressResponse)
async def get_progress(
        experience_id: str,
        session: AsyncSession = Depends(get_session)) -> ReaderProgressResponse:
    progress = await progress_service.get_progress(session, experience_id)
    return progress_service.to_response(experience_id, progress)


@router.put("/{experience_id}/progress", response_model=ReaderProgressResponse)
async def update_progress(
        experience_id: str,
        req: ReaderProgressUpdate,
        session: AsyncSession = Depends(get_session)) -> ReaderProgressResponse:
    progress = await progress_service.upsert_progress(
        session, experience_id, req)
    return progress_service.to_response(experience_id, progress)
