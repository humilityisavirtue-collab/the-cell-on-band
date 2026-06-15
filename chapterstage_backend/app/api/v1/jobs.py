"""jobs.py — §9.4/9.5/9.6/9.7/9.9: create a job (and LAUNCH it), status, SSE
progress stream, agent trace, recent-jobs list."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.database import get_session
from app.models import AgentTraceEvent, Chapter, GenerationJob
from app.schemas import JobCreateRequest, JobCreateResponse, JobStatusResponse
from app.services import job_service, live_progress
from app.services.generation_runner import run_job
from app.services.sse_bus import bus

router = APIRouter(prefix="/generation-jobs", tags=["jobs"])


def _base(job_id: str) -> str:
    return "%s/api/v1/generation-jobs/%s" % (settings.API_BASE_URL, job_id)


@router.post("", response_model=JobCreateResponse, status_code=202)
async def create_job(
        req: JobCreateRequest,
        session: AsyncSession = Depends(get_session)) -> JobCreateResponse:
    job = await job_service.create_job(session, req)
    # LAUNCH the generation loop (fire-and-forget; progress via SSE + polling).
    asyncio.create_task(run_job(job.id))
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
    # overlay live in-flight progress when the job is still running
    status, progress, step = job.status, job.progress, job.current_step
    if job.status not in ("completed", "failed"):
        live = live_progress.get(job_id)
        if live:
            status, progress, step = live["status"], live["progress"], live["current_step"]
    return JobStatusResponse(
        job_id=job.id, chapter_id=job.chapter_id, status=status,
        progress=progress, current_step=step,
        band_room_id=job.band_room_id, experience_id=job.experience_id,
        public_url=job.public_url, error=error,
        created_at=job.created_at, updated_at=job.updated_at)


@router.get("/{job_id}/events")
async def stream_events(job_id: str):
    """§9.6 SSE: text/event-stream of job_progress / agent_message /
    experience_ready / job_failed events for this job."""
    async def gen():
        async for event in bus.subscribe(job_id):
            yield {"event": event["event"], "data": json.dumps(event["data"])}
    return EventSourceResponse(gen())


@router.get("/{job_id}/trace")
async def get_trace(job_id: str, session: AsyncSession = Depends(get_session)):
    """§9.7: the persisted agent trace for the job (oldest first)."""
    await job_service.get_job(session, job_id)            # 404s if unknown
    rows = (await session.execute(
        select(AgentTraceEvent).where(AgentTraceEvent.job_id == job_id)
        .order_by(AgentTraceEvent.created_at))).scalars().all()
    job = await session.get(GenerationJob, job_id)
    return {
        "job_id": job_id, "band_room_id": job.band_room_id if job else None,
        "events": [{"id": r.id, "agent_name": r.agent_name,
                    "event_type": r.event_type, "title": r.title,
                    "message": r.message, "payload": r.payload,
                    "created_at": r.created_at} for r in rows]}


@router.get("")
async def list_jobs(limit: int = 20, offset: int = 0,
                    session: AsyncSession = Depends(get_session)):
    """§9.9: recent jobs with chapter title + public URL."""
    total = await job_service.count_jobs(session)
    rows = (await session.execute(
        select(GenerationJob, Chapter.title)
        .join(Chapter, Chapter.id == GenerationJob.chapter_id)
        .order_by(desc(GenerationJob.created_at))
        .limit(limit).offset(offset))).all()
    return {
        "items": [{"job_id": j.id, "chapter_title": title, "status": j.status,
                   "progress": j.progress, "public_url": j.public_url,
                   "created_at": j.created_at} for j, title in rows],
        "limit": limit, "offset": offset, "total": total}
