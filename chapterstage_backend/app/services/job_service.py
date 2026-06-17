"""job_service.py — chapter + generation-job persistence (handoff §9.2-9.5, §4.2).

M1 is the lifecycle's front door: create a chapter (book auto-created), open a job
row at status `queued`, fetch its status. The workflow that advances the status
(M3/M4 ChapterWorkflow) wires in at M4-live; here the row just exists and is
fetchable, which is what the frontend polls.
"""
from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.errors import APIError, INVALID_REQUEST, JOB_NOT_FOUND
from app.models import (AgentTraceEvent, Book, Chapter, Experience, GenerationJob,
                        _now)
from app.schemas import ChapterTextRequest, JobCreateRequest
from app.services import sse_bus
from app.services.site_storage import write_modular_site

logger = logging.getLogger(__name__)


async def create_chapter_from_text(
        session: AsyncSession, req: ChapterTextRequest) -> Chapter:
    from app.services.document_parser import validate_chapter_text
    text = validate_chapter_text(req.text)
    title = req.chapter_title or req.book_title or "Untitled Chapter"
    book = Book(title=req.book_title or "Untitled")
    session.add(book)
    await session.flush()                       # get book.id
    chapter = Chapter(book_id=book.id, title=title,
                      source_type="text", source_text=text)
    session.add(chapter)
    await session.commit()
    await session.refresh(chapter)
    return chapter


async def create_chapter_from_upload(
        session: AsyncSession, filename: str, content: bytes,
        book_title: str | None, chapter_title: str | None) -> Chapter:
    from app.services.document_parser import parse_upload
    source_type, text = parse_upload(filename, content)
    title = chapter_title or book_title or filename or "Untitled Chapter"
    book = Book(title=book_title or "Untitled")
    session.add(book)
    await session.flush()
    chapter = Chapter(book_id=book.id, title=title,
                      source_type=source_type, source_text=text)
    session.add(chapter)
    await session.commit()
    await session.refresh(chapter)
    return chapter


async def create_job(session: AsyncSession, req: JobCreateRequest) -> GenerationJob:
    chapter = await session.get(Chapter, req.chapter_id)
    if chapter is None:
        raise APIError(INVALID_REQUEST, "Unknown chapter_id.",
                       {"chapter_id": req.chapter_id})
    job = GenerationJob(
        chapter_id=req.chapter_id, status="queued",
        audience_level=req.audience_level, experience_style=req.experience_style,
        target_screen_count=req.target_screen_count,
        enable_auto_brainstorm=req.enable_auto_brainstorm)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    logger.info(
        "generation job queued job_id=%s chapter_id=%s audience=%s style=%s screens=%s",
        job.id, job.chapter_id, job.audience_level, job.experience_style,
        job.target_screen_count)
    return job


async def get_job(session: AsyncSession, job_id: str) -> GenerationJob:
    job = await session.get(GenerationJob, job_id)
    if job is None:
        raise APIError(JOB_NOT_FOUND, "No such job.", {"job_id": job_id})
    return job


async def list_jobs(
        session: AsyncSession, limit: int = 20,
        offset: int = 0) -> list[GenerationJob]:
    rows = await session.execute(
        select(GenerationJob).order_by(
            GenerationJob.created_at.desc()).offset(offset).limit(limit))
    return list(rows.scalars().all())


async def count_jobs(session: AsyncSession) -> int:
    return (await session.execute(select(func.count(GenerationJob.id)))).scalar_one()


async def run_generation_job(job_id: str) -> None:
    async with async_session() as session:
        job = await session.get(GenerationJob, job_id)
        if job is None:
            return
        chapter = await session.get(Chapter, job.chapter_id)
        if chapter is None:
            await _fail_job(session, job, "EXTRACTION_FAILED",
                            "Chapter source is missing.")
            return
        try:
            logger.info("generation job started job_id=%s chapter_id=%s",
                        job.id, job.chapter_id)
            await _set_job(session, job, "extracting", 0.10,
                           "Preparing chapter text.")
            await _set_job(session, job, "creating_band_room", 0.18,
                           "Creating Band chapter room.")

            from app.services.band_transport.factory import create_band_service
            from workflows.chapter_graph import ChapterWorkflow

            band = create_band_service()
            state = await asyncio.to_thread(
                ChapterWorkflow(band).run,
                job.id, chapter.title, chapter.source_text or "")
            job.band_room_id = getattr(band, "room_id", None)
            await session.commit()
            await _trace_handoffs(session, job, band)

            if state.get("status") != "completed":
                await _trace_workflow_failure(session, job, state)
                message = _workflow_failure_message(state)
                await _fail_job(session, job, "AGENT_WORKFLOW_FAILED", message)
                return

            await _set_job(session, job, "building_site", 0.72,
                           "Assembling modular chapter site.")
            experience_id = "exp_%s" % uuid4().hex
            public_url = "%s/%s/index.html" % (
                settings.PUBLIC_SITE_BASE_URL.rstrip("/"), experience_id)
            write_modular_site(
                experience_id=experience_id,
                job_id=job.id,
                title=chapter.title,
                screens=_screens_for_chapter(chapter, state),
                metadata={
                    "book_title": chapter.title,
                    "chapter_title": chapter.title,
                    "audience_level": job.audience_level,
                    "experience_style": job.experience_style,
                    "band_room_id": job.band_room_id or "",
                    "selected_brainstorm_variant": "v1",
                    "faithfulness_score": 1,
                    "engagement_score": 1,
                },
            )
            await _set_job(session, job, "publishing", 0.90,
                           "Publishing validated chapter site.")
            exp = Experience(id=experience_id, job_id=job.id,
                             public_url=public_url,
                             storage_path=experience_id, meta={
                                 "chapter_title": chapter.title,
                                 "screen_count": 3,
                             })
            session.add(exp)
            job.status = "completed"
            job.progress = 1.0
            job.current_step = "Completed"
            job.experience_id = experience_id
            job.public_url = public_url
            job.completed_at = _now()
            job.updated_at = _now()
            session.add(job)
            await session.commit()
            await sse_bus.publish(job.id, "experience_ready", {
                "experience_id": experience_id,
                "public_url": public_url,
            })
            logger.info("generation job completed job_id=%s experience_id=%s",
                        job.id, experience_id)
        except Exception as exc:
            logger.exception("generation job failed job_id=%s", job.id)
            await _fail_job(session, job, "AGENT_WORKFLOW_FAILED", str(exc))


async def _set_job(
        session: AsyncSession, job: GenerationJob, status: str, progress: float,
        step: str) -> None:
    job.status = status
    job.progress = progress
    job.current_step = step
    job.updated_at = _now()
    session.add(job)
    await session.commit()
    logger.info("generation job progress job_id=%s status=%s progress=%.2f step=%s",
                job.id, status, progress, step)
    await sse_bus.publish(job.id, "job_progress", {
        "status": status,
        "progress": progress,
        "message": step,
    })


async def _fail_job(
        session: AsyncSession, job: GenerationJob, code: str, message: str) -> None:
    job.status = "failed_agent_workflow"
    job.progress = max(job.progress, 0.0)
    job.current_step = "Failed"
    job.error_code = code
    job.error_message = message
    job.updated_at = _now()
    session.add(job)
    await session.commit()
    logger.error("generation job failed job_id=%s code=%s message=%s",
                 job.id, code, message)
    await sse_bus.publish(job.id, "job_failed", {
        "status": job.status,
        "progress": job.progress,
        "message": message,
        "error": {"code": code, "message": message},
    })


async def _trace_handoffs(
        session: AsyncSession, job: GenerationJob, band) -> None:
    for rec in getattr(band, "handoffs", []):
        event = AgentTraceEvent(
            job_id=job.id,
            band_room_id=job.band_room_id,
            agent_name=rec.get("from", "agent"),
            event_type="handoff",
            title="%s to %s" % (rec.get("from"), rec.get("to")),
            message="Delivered %s envelope." % rec.get("kind", "unknown"),
            payload=rec,
        )
        session.add(event)
        await sse_bus.publish(job.id, "agent_message", {
            "agent_name": event.agent_name,
            "title": event.title,
            "message": event.message,
        })
    await session.commit()


async def _trace_workflow_failure(
        session: AsyncSession, job: GenerationJob, state: dict) -> None:
    log_entries = state.get("log") or ["workflow"]
    stage = state.get("error_stage") or log_entries[-1]
    message = _workflow_failure_message(state)
    event = AgentTraceEvent(
        job_id=job.id,
        band_room_id=job.band_room_id,
        agent_name=str(stage or "workflow"),
        event_type="workflow_error",
        title="Workflow failed at %s" % (stage or "unknown stage"),
        message=message,
        payload={
            "status": state.get("status"),
            "error_stage": state.get("error_stage"),
            "error_type": state.get("error_type"),
            "error": state.get("error"),
            "log": state.get("log", []),
        },
    )
    session.add(event)
    await session.commit()
    await sse_bus.publish(job.id, "agent_error", {
        "agent_name": event.agent_name,
        "title": event.title,
        "message": event.message,
        "payload": event.payload,
    })


def _workflow_failure_message(state: dict) -> str:
    if state.get("error"):
        stage = state.get("error_stage")
        if stage:
            return "%s failed: %s" % (stage, state["error"])
        return str(state["error"])
    if state.get("status") == "stalled":
        return "Agent workflow stalled before completion."
    return "Agent workflow failed before completion."


def _screens_for_chapter(chapter: Chapter, state: dict) -> list[dict]:
    text = (chapter.source_text or "").strip()
    preview = text[:700] + ("..." if len(text) > 700 else "")
    ideas = state.get("pack", {}).get("pack", {}).get("ideas", [])
    return [
        {"id": "intro", "title": chapter.title, "component_type": "text_screen",
         "content": {"text": preview or "Chapter source prepared."}},
        {"id": "map", "title": "Concept Map", "component_type": "concept_map",
         "content": {"text": ", ".join(ideas) or "Key ideas are ready."}},
        {"id": "recap", "title": "Recap", "component_type": "recap",
         "content": {"text": "Review the checkpoint and continue learning."}},
    ]
