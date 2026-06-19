"""job_service.py — chapter + generation-job persistence (handoff §9.2-9.5, §4.2).

M1 is the lifecycle's front door: create a chapter (book auto-created), open a job
row at status `queued`, fetch its status. The workflow that advances the status
(M3/M4 ChapterWorkflow) wires in at M4-live; here the row just exists and is
fetchable, which is what the frontend polls.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.errors import APIError, INVALID_REQUEST, JOB_ALREADY_RUNNING, JOB_NOT_FOUND
from app.models import (AgentTraceEvent, Book, Chapter, Experience, GenerationJob,
                        _now)
from app.schemas import ChapterTextRequest, JobCreateRequest
from app.services import sse_bus
from app.services.site_storage import write_modular_site

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"completed", "failed_agent_workflow", "cancelled"}


def _elapsed_seconds(job: GenerationJob) -> int:
    return int((datetime.utcnow() - job.created_at).total_seconds())


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


async def request_cancel_job(session: AsyncSession, job_id: str) -> GenerationJob:
    job = await get_job(session, job_id)
    if job.status == "cancelled":
        return job
    if _is_terminal(job.status):
        raise APIError(
            JOB_ALREADY_RUNNING,
            "Terminal job cannot be cancelled.",
            {"job_id": job_id, "status": job.status},
        )
    job.cancel_requested_at = job.cancel_requested_at or _now()
    if job.status == "queued":
        return await _complete_cancelled_job(session, job)
    job.status = "cancelling"
    job.current_step = "Cancelling"
    job.updated_at = _now()
    session.add(job)
    await session.commit()
    await session.refresh(job)
    elapsed = _elapsed_seconds(job)
    await sse_bus.publish(job.id, "job_progress", {
        "status": job.status,
        "progress": job.progress,
        "message": "Cancellation requested.",
        "elapsed_seconds": elapsed,
    })
    logger.info("generation job cancellation requested job_id=%s", job.id)
    return job


async def retry_job(session: AsyncSession, job_id: str) -> GenerationJob:
    original = await get_job(session, job_id)
    if not _is_terminal(original.status):
        raise APIError(
            JOB_ALREADY_RUNNING,
            "Only terminal jobs can be retried.",
            {"job_id": job_id, "status": original.status},
        )
    req = JobCreateRequest(
        chapter_id=original.chapter_id,
        audience_level=original.audience_level,
        experience_style=original.experience_style,
        target_screen_count=original.target_screen_count,
        enable_auto_brainstorm=original.enable_auto_brainstorm,
    )
    return await create_job(session, req)


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
        if await _finish_if_cancel_requested(session, job):
            return
        chapter = await session.get(Chapter, job.chapter_id)
        if chapter is None:
            await _fail_job(session, job, "EXTRACTION_FAILED",
                            "Chapter source is missing.")
            return
        band = None
        try:
            logger.info("generation job started job_id=%s chapter_id=%s",
                        job.id, job.chapter_id)
            if await _finish_if_cancel_requested(session, job):
                return
            await _set_job(session, job, "extracting", 0.10,
                           "Preparing chapter text.")
            if await _finish_if_cancel_requested(session, job):
                return
            await _set_job(session, job, "creating_band_room", 0.18,
                           "Creating Band chapter room.")
            if await _finish_if_cancel_requested(session, job):
                return

            from app.services.band_transport.factory import create_band_service
            from workflows.chapter_graph import ChapterWorkflow

            band = create_band_service()
            loop = asyncio.get_running_loop()

            async def _persist_agent_stage(
                    stage_index: int, total_stages: int, role: str,
                    input_envelope: dict | None, output_envelope: dict | None) -> None:
                progress = 0.20 + (stage_index / total_stages) * 0.48
                elapsed = int((datetime.utcnow() - job.created_at).total_seconds())
                kind = (output_envelope or {}).get("kind", "unknown")
                to_role = (output_envelope or {}).get("to", "next")
                title = "%s agent completed" % role
                message = "Produced %s envelope for %s" % (kind, to_role)
                payload = {
                    "stage_index": stage_index,
                    "total_stages": total_stages,
                    "input": input_envelope,
                    "output": output_envelope,
                }
                async with async_session() as sess:
                    event = AgentTraceEvent(
                        job_id=job.id,
                        band_room_id=job.band_room_id,
                        agent_name=role,
                        event_type="agent_message",
                        title=title,
                        message=message,
                        payload=payload,
                        elapsed_seconds=elapsed,
                    )
                    sess.add(event)
                    await sess.commit()
                await sse_bus.publish(job.id, "agent_message", {
                    "agent_id": role,
                    "agent_name": role,
                    "event_type": "agent_message",
                    "title": title,
                    "message": message,
                    "payload": payload,
                    "progress": progress,
                    "elapsed_seconds": elapsed,
                    "status": "running",
                })

            def _on_stage_complete(
                    stage_index: int, total_stages: int, role: str,
                    input_envelope: dict | None, output_envelope: dict | None) -> None:
                asyncio.run_coroutine_threadsafe(
                    _persist_agent_stage(
                        stage_index, total_stages, role, input_envelope, output_envelope),
                    loop,
                )

            state = await asyncio.to_thread(
                ChapterWorkflow(band).run,
                job.id, chapter.title, chapter.source_text or "",
                audience_level=job.audience_level,
                experience_style=job.experience_style,
                target_screen_count=job.target_screen_count,
                on_stage_complete=_on_stage_complete)
            job.band_room_id = getattr(band, "room_id", None)
            await session.commit()
            await _trace_handoffs(session, job, band)
            if await _finish_if_cancel_requested(session, job):
                return

            if state.get("status") != "completed":
                await _trace_workflow_failure(session, job, state)
                message = _workflow_failure_message(state)
                await _fail_job(session, job, "AGENT_WORKFLOW_FAILED", message)
                return

            await _set_job(session, job, "building_site", 0.72,
                           "Assembling modular chapter site.")
            if await _finish_if_cancel_requested(session, job):
                return
            experience_id = "exp_%s" % uuid4().hex
            public_url = "%s/%s/index.html" % (
                settings.PUBLIC_SITE_BASE_URL.rstrip("/"), experience_id)
            screens = _screens_for_chapter(chapter, state)
            if await _finish_if_cancel_requested(session, job):
                return
            write_modular_site(
                experience_id=experience_id,
                job_id=job.id,
                title=chapter.title,
                screens=screens,
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
            if await _finish_if_cancel_requested(session, job):
                return
            await _set_job(session, job, "publishing", 0.90,
                           "Publishing validated chapter site.")
            if await _finish_if_cancel_requested(session, job):
                return
            exp = Experience(id=experience_id, job_id=job.id,
                             public_url=public_url,
                             storage_path=experience_id, meta={
                                 "chapter_title": chapter.title,
                                 "screen_count": len(screens),
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
            elapsed = _elapsed_seconds(job)
            await sse_bus.publish(job.id, "experience_ready", {
                "experience_id": experience_id,
                "public_url": public_url,
                "elapsed_seconds": elapsed,
            })
            logger.info("generation job completed job_id=%s experience_id=%s elapsed=%s",
                        job.id, experience_id, elapsed)
        except Exception as exc:
            if await _finish_if_cancel_requested(session, job):
                return
            logger.exception("generation job failed job_id=%s", job.id)
            await _fail_job(session, job, "AGENT_WORKFLOW_FAILED", str(exc))
        finally:
            _close_band_transport(band)


def _is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def _close_band_transport(band) -> None:
    transport = getattr(band, "transport", None)
    close = getattr(transport, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception as exc:
        logger.warning("failed to close Band transport cleanly: %s", exc)


async def _finish_if_cancel_requested(
        session: AsyncSession, job: GenerationJob) -> bool:
    await session.refresh(job)
    if job.status == "cancelled":
        return True
    if job.cancel_requested_at is None and job.status != "cancelling":
        return False
    await _complete_cancelled_job(session, job)
    return True


async def _complete_cancelled_job(
        session: AsyncSession, job: GenerationJob) -> GenerationJob:
    if job.status == "cancelled":
        return job
    now = _now()
    job.status = "cancelled"
    job.current_step = "Cancelled"
    job.completed_at = job.completed_at or now
    job.updated_at = now
    session.add(job)
    await session.commit()
    await session.refresh(job)
    elapsed = _elapsed_seconds(job)
    logger.info("generation job cancelled job_id=%s", job.id)
    await sse_bus.publish(job.id, "job_cancelled", {
        "status": job.status,
        "progress": job.progress,
        "message": "Job cancelled.",
        "elapsed_seconds": elapsed,
    })
    return job


async def _set_job(
        session: AsyncSession, job: GenerationJob, status: str, progress: float,
        step: str) -> None:
    job.status = status
    job.progress = progress
    job.current_step = step
    job.updated_at = _now()
    session.add(job)
    await session.commit()
    elapsed = _elapsed_seconds(job)
    logger.info("generation job progress job_id=%s status=%s progress=%.2f step=%s elapsed=%s",
                job.id, status, progress, step, elapsed)
    await sse_bus.publish(job.id, "job_progress", {
        "status": status,
        "progress": progress,
        "message": step,
        "elapsed_seconds": elapsed,
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
    elapsed = _elapsed_seconds(job)
    logger.error("generation job failed job_id=%s code=%s message=%s elapsed=%s",
                 job.id, code, message, elapsed)
    await sse_bus.publish(job.id, "job_failed", {
        "status": job.status,
        "progress": job.progress,
        "message": message,
        "error": {"code": code, "message": message},
        "elapsed_seconds": elapsed,
    })


async def _trace_handoffs(
        session: AsyncSession, job: GenerationJob, band) -> None:
    elapsed = _elapsed_seconds(job)
    for rec in getattr(band, "handoffs", []):
        event = AgentTraceEvent(
            job_id=job.id,
            band_room_id=job.band_room_id,
            agent_name=rec.get("from", "agent"),
            event_type="handoff",
            title="%s to %s" % (rec.get("from"), rec.get("to")),
            message="Delivered %s envelope." % rec.get("kind", "unknown"),
            payload=rec,
            elapsed_seconds=elapsed,
        )
        session.add(event)
        await sse_bus.publish(job.id, "agent_message", {
            "agent_id": rec.get("from", "agent"),
            "agent_name": event.agent_name,
            "event_type": "handoff",
            "title": event.title,
            "message": event.message,
            "payload": event.payload,
            "elapsed_seconds": elapsed,
        })
    await session.commit()


async def _trace_workflow_failure(
        session: AsyncSession, job: GenerationJob, state: dict) -> None:
    log_entries = state.get("log") or ["workflow"]
    stage = state.get("error_stage") or log_entries[-1]
    message = _workflow_failure_message(state)
    elapsed = _elapsed_seconds(job)
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
            "transport_error": state.get("transport_error"),
            "log": state.get("log", []),
        },
        elapsed_seconds=elapsed,
    )
    session.add(event)
    await session.commit()
    await sse_bus.publish(job.id, "agent_error", {
        "agent_name": event.agent_name,
        "title": event.title,
        "message": event.message,
        "payload": event.payload,
        "elapsed_seconds": elapsed,
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
    storyboard = _payload(state.get("storyboard"), "storyboard")
    scenes = storyboard.get("scenes") if isinstance(storyboard, dict) else None
    screens = []
    if isinstance(scenes, list):
        for index, scene in enumerate(scenes, start=1):
            screen = _screen_from_scene(scene, index, chapter)
            if screen is not None:
                screens.append(screen)
    if screens:
        return screens
    return _fallback_screens_for_chapter(chapter, state)


def _screen_from_scene(scene, index: int, chapter: Chapter) -> dict | None:
    if not isinstance(scene, dict):
        return None
    component_type = str(
        scene.get("component_type") or scene.get("kind")
        or "narrative_scene").strip() or "narrative_scene"
    content = scene.get("content")
    if not isinstance(content, dict):
        content = {}
    if not content:
        content = {"text": str(scene.get("description") or "").strip()}
    if not any(_truthy_content(v) for v in content.values()):
        content = {"text": (chapter.source_text or "").strip()[:700]}
    return {
        "id": str(scene.get("id") or "screen_%d" % index),
        "title": str(scene.get("title") or _component_title(component_type, index)),
        "component_type": component_type,
        "content": content,
        "interactions": scene.get("interactions")
        if isinstance(scene.get("interactions"), list) else [],
    }


def _fallback_screens_for_chapter(chapter: Chapter, state: dict) -> list[dict]:
    text = (chapter.source_text or "").strip()
    preview = text[:700] + ("..." if len(text) > 700 else "")
    pack = _payload(state.get("pack"), "pack")
    ideas = [str(i) for i in pack.get("ideas", []) if str(i).strip()]
    sections = [str(s) for s in pack.get("sections", []) if str(s).strip()]
    nodes = [
        {"label": idea, "detail": sections[i % len(sections)] if sections else ""}
        for i, idea in enumerate(ideas[:6])
    ]
    connections = [
        {"from": ideas[i], "to": ideas[i + 1], "label": "builds toward"}
        for i in range(max(0, min(len(ideas), 5) - 1))
    ]
    return [
        {"id": "intro", "title": chapter.title, "component_type": "narrative_scene",
         "content": {
             "text": preview or "Chapter source prepared.",
             "beats": sections[:4],
             "callout": ideas[0] if ideas else "",
         }},
        {"id": "concept_map", "title": "Concept map",
         "component_type": "concept_map",
         "content": {
             "text": "Key ideas are ready.",
             "nodes": nodes,
             "connections": connections,
         }},
        {"id": "recap", "title": "Recap", "component_type": "recap",
         "content": {
             "text": "Review the checkpoint and continue learning.",
             "highlights": ideas[:4],
         }},
    ]


def _payload(value, key: str) -> dict:
    if isinstance(value, dict) and isinstance(value.get(key), dict):
        return value[key]
    if isinstance(value, dict):
        return value
    return {}


def _truthy_content(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return value is not None


def _component_title(component_type: str, index: int) -> str:
    labels = {
        "narrative_scene": "Scene",
        "text_screen": "Scene",
        "concept_map": "Concept map",
        "process_flow": "Process flow",
        "quiz": "Checkpoint",
        "recap": "Recap",
    }
    return "%s %d" % (labels.get(component_type, "Screen"), index)
