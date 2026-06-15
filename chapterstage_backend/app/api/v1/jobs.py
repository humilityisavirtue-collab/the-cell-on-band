"""jobs.py — generation jobs: create, status, events, trace."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.database import get_session
from app.models import AgentTraceEvent
from app.schemas import (JobCreateRequest, JobCreateResponse, JobStatusResponse,
                         JobTraceResponse, TraceEventResponse)
from app.services import job_service, sse_bus

router = APIRouter(prefix="/generation-jobs", tags=["jobs"])


def _base(job_id: str) -> str:
    return "%s/api/v1/generation-jobs/%s" % (settings.API_BASE_URL, job_id)


@router.post("", response_model=JobCreateResponse, status_code=202)
async def create_job(
        req: JobCreateRequest,
        background_tasks: BackgroundTasks,
        session: AsyncSession = Depends(get_session)) -> JobCreateResponse:
    job = await job_service.create_job(session, req)
    background_tasks.add_task(job_service.run_generation_job, job.id)
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


@router.get("/{job_id}/events")
async def stream_job_events(
        job_id: str,
        session: AsyncSession = Depends(get_session)) -> EventSourceResponse:
    await job_service.get_job(session, job_id)
    return EventSourceResponse(sse_bus.stream(job_id))


@router.get("/{job_id}/trace", response_model=JobTraceResponse)
async def get_trace(
        job_id: str,
        session: AsyncSession = Depends(get_session)) -> JobTraceResponse:
    job = await job_service.get_job(session, job_id)
    rows = (await session.execute(
        select(AgentTraceEvent).where(
            AgentTraceEvent.job_id == job_id).order_by(
                AgentTraceEvent.created_at))).scalars().all()
    return JobTraceResponse(
        job_id=job_id,
        band_room_id=job.band_room_id,
        events=[TraceEventResponse(
            id=e.id, agent_name=e.agent_name, event_type=e.event_type,
            title=e.title, message=e.message, payload=e.payload,
            created_at=e.created_at) for e in rows])
