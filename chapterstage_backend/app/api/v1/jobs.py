"""jobs.py — handoff §9.4/9.5: create a generation job, fetch its status."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.schemas import JobCreateRequest, JobCreateResponse, JobStatusResponse
from app.services import job_service

router = APIRouter(prefix="/generation-jobs", tags=["jobs"])


def _base(job_id: str) -> str:
    return "%s/api/v1/generation-jobs/%s" % (settings.API_BASE_URL, job_id)


@router.post("", response_model=JobCreateResponse, status_code=202)
async def create_job(
        req: JobCreateRequest,
        session: AsyncSession = Depends(get_session)) -> JobCreateResponse:
    job = await job_service.create_job(session, req)
    return JobCreateResponse(
        job_id=job.id, chapter_id=job.chapter_id, status=job.status,
        status_url=_base(job.id), events_url=_base(job.id) + "/events")


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(
        job_id: str,
        session: AsyncSession = Depends(get_session)) -> JobStatusResponse:
    job = await job_service.get_job(session, job_id)
    error = None
    if job.error_code:
        error = {"code": job.error_code, "message": job.error_message or ""}
    return JobStatusResponse(
        job_id=job.id, chapter_id=job.chapter_id, status=job.status,
        progress=job.progress, current_step=job.current_step,
        band_room_id=job.band_room_id, experience_id=job.experience_id,
        public_url=job.public_url, error=error,
        created_at=job.created_at, updated_at=job.updated_at)
