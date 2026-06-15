"""generation_runner.py — drive one job from queued to completed (the loop).

This is the wiring the repo was missing: create_job now launches run_job() as a
background task. It runs the kill-tested ChapterWorkflow (band_service is the
load-bearing handoff seam — UNCHANGED, so the M4 invariant still holds), streams
each stage over SSE + persists trace events, then builds the real site from the
storyboard, validates+publishes it, and writes the Experience row + final job
state.

The workflow body is sync (NIM calls block); it runs in a worker thread via
asyncio.to_thread so the event loop stays free to flush SSE. The per-stage
callback is thread-safe: it only touches sse_bus (loop-hops internally) and the
live_progress registry.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from app.database import async_session
from app.errors import SITE_VALIDATION_FAILED
from app.models import AgentTraceEvent, Chapter, Experience, GenerationJob
from app.services import live_progress
from app.services.sse_bus import bus

_BACKEND = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_BACKEND))
import band_service as band_service_mod  # noqa: E402
from workflows.chapter_graph import ChapterWorkflow  # noqa: E402
from workflows.site_builder import build_site  # noqa: E402
from app.services.site_storage import publish_site  # noqa: E402

# stage role -> (job status, progress, human step)
_STAGE_META = {
    "structure":  ("structuring",   0.35, "Structure agent mapped the chapter"),
    "brainstorm": ("brainstorming", 0.55, "Brainstorm agent chose a presentation"),
    "visual":     ("building_site", 0.75, "Visual builder drafted the storyboard"),
    "verifier":   ("verifying",     0.90, "Verifier checked source faithfulness"),
}


async def run_job(job_id: str) -> None:
    """Entry point the API schedules. Owns all DB writes for this job. A crash
    anywhere here must never leave a job hung mid-progress: the outer guard marks
    it failed + emits job_failed + clears live progress, so a poll/SSE client
    always reaches a terminal state."""
    try:
        await _run_job_inner(job_id)
    except Exception as e:
        from app.errors import INTERNAL_ERROR
        live_progress.clear(job_id)
        try:
            async with async_session() as session:
                job = await session.get(GenerationJob, job_id)
                if job is not None:
                    await _fail(session, job, INTERNAL_ERROR, "Generation crashed: %s" % e)
        finally:
            bus.publish(job_id, "job_failed",
                        {"job_id": job_id,
                         "error": {"code": "INTERNAL_ERROR", "message": str(e)}})
            bus.mark_done(job_id)


async def _run_job_inner(job_id: str) -> None:
    async with async_session() as session:
        job = await session.get(GenerationJob, job_id)
        if job is None:
            return
        chapter = await session.get(Chapter, job.chapter_id)
        source_text = (chapter.source_text if chapter else "") or ""
        source_ref = (chapter.title if chapter else None) or job.chapter_id
        params = {"audience_level": job.audience_level,
                  "experience_style": job.experience_style,
                  "target_screen_count": job.target_screen_count,
                  "enable_auto_brainstorm": job.enable_auto_brainstorm}
        await _set(session, job, status="creating_band_room", progress=0.1,
                   current_step="Opening the Band room and recruiting agents")

    bus.publish(job_id, "job_progress",
                {"job_id": job_id, "status": "creating_band_room",
                 "progress": 0.1, "message": "Opening the Band room"})

    # Live Band room when opted in (CHAPTERSTAGE_BAND_LIVE=1); else the in-memory
    # kill-test twin. Either way band_service is the load-bearing handoff seam.
    transport = None
    if os.environ.get("CHAPTERSTAGE_BAND_LIVE", "").lower() in ("1", "true", "yes", "on"):
        from app.services.band_live import BandRoomTransport
        transport = BandRoomTransport()
    band = band_service_mod.BandService(transport=transport)
    wf = ChapterWorkflow(band)
    traces: list[dict] = []

    def on_stage(role, to_role, env, state):
        status, progress, step = _STAGE_META.get(
            role, (role, 0.5, "%s finished" % role))
        live_progress.update(job_id, status, progress, step)
        bus.publish(job_id, "job_progress",
                    {"job_id": job_id, "status": status, "progress": progress,
                     "message": step})
        bus.publish(job_id, "agent_message",
                    {"job_id": job_id, "agent_name": "%s agent" % role.title(),
                     "title": step, "message": _summarize(env)})
        traces.append({"agent_name": "%s agent" % role.title(),
                       "event_type": env.get("kind", "handoff"),
                       "title": step, "message": _summarize(env),
                       "payload": env})

    # the blocking workflow runs off the event loop
    state = await asyncio.to_thread(
        wf.run, job_id, source_ref,
        source_text=source_text, params=params, on_stage=on_stage)

    state["band_room_id"] = getattr(band, "room_id", None)
    await _finalize(job_id, state, params, traces)
    live_progress.clear(job_id)
    bus.mark_done(job_id)


async def _finalize(job_id, state, params, traces):
    async with async_session() as session:
        job = await session.get(GenerationJob, job_id)
        if job is None:
            return
        room_id = state.get("band_room_id")
        job.band_room_id = room_id

        # persist the trace (every stage, with its envelope payload)
        for t in traces:
            session.add(AgentTraceEvent(
                job_id=job_id, band_room_id=room_id, agent_name=t["agent_name"],
                event_type=t["event_type"], title=t["title"],
                message=t["message"], payload=t["payload"]))

        if state.get("status") != "completed":
            # stalled (Band severed) or a node emitted an invalid envelope
            code, msg = _failure(state)
            await _fail(session, job, code, msg)
            bus.publish(job_id, "job_failed",
                        {"job_id": job_id, "error": {"code": code, "message": msg}})
            return

        # --- build + publish the real site ---
        await _set(session, job, status="publishing", progress=0.95,
                   current_step="Building and validating the site")
        bus.publish(job_id, "job_progress",
                    {"job_id": job_id, "status": "publishing", "progress": 0.95,
                     "message": "Building and validating the site"})

        pack = state.get("pack", {}).get("pack", {})
        storyboard = state.get("storyboard", {}).get("storyboard", {})
        verdict = state.get("module", {}).get("verdict", {})
        score = state.get("score", {}).get("score", {})
        experience_id = "exp_" + job_id.replace("-", "")[:16]
        meta = {
            "experience_id": experience_id, "job_id": job_id,
            "book_title": params.get("book_title", ""),
            "chapter_title": state.get("source_ref", ""),
            "band_room_id": room_id,
            "selected_brainstorm_variant": score.get("variant_id", ""),
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        files = build_site(storyboard, pack, verdict, meta)
        report = publish_site(experience_id, files)

        if not report["passed"]:
            msg = "Generated site failed validation: " + "; ".join(
                "%s(%s)" % (v["check"], v["detail"]) for v in report["violations"][:6])
            await _fail(session, job, SITE_VALIDATION_FAILED, msg)
            bus.publish(job_id, "job_failed",
                        {"job_id": job_id,
                         "error": {"code": SITE_VALIDATION_FAILED, "message": msg}})
            return

        session.add(Experience(
            id=experience_id, job_id=job_id, public_url=report["public_url"],
            storage_path=report["storage_path"],
            meta={**meta, "faithfulness_score": verdict.get("faithfulness_score"),
                  "engagement_score": verdict.get("engagement_score"),
                  "screen_count": storyboard.get("screen_count")}))

        job.status = "completed"
        job.progress = 1.0
        job.current_step = "Completed"
        job.experience_id = experience_id
        job.public_url = report["public_url"]
        job.completed_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        await session.commit()

        bus.publish(job_id, "experience_ready",
                    {"job_id": job_id, "experience_id": experience_id,
                     "public_url": report["public_url"]})


def _summarize(env: dict) -> str:
    kind = env.get("kind")
    if kind == "knowledge_pack":
        p = env.get("pack", {})
        return "Mapped %d sections, %d key ideas." % (
            len(p.get("sections", [])), len(p.get("ideas", [])))
    if kind == "brainstorm_score":
        s = env.get("score", {})
        return "Chose '%s' (%s), score %.2f." % (
            s.get("title", "?"), s.get("format", "?"), s.get("value", 0))
    if kind == "storyboard":
        sb = env.get("storyboard", {})
        return "Drafted %d interactive scenes." % len(sb.get("scenes", []))
    if kind == "module":
        v = env.get("verdict", {})
        return "Faithfulness %s (%.2f)." % (
            v.get("result", "?"), v.get("faithfulness_score", 0))
    return kind or "handoff"


def _failure(state) -> tuple[str, str]:
    from app.errors import AGENT_WORKFLOW_FAILED
    if state.get("status") == "stalled":
        return AGENT_WORKFLOW_FAILED, "Band transport severed — loop stalled (no module)."
    return AGENT_WORKFLOW_FAILED, state.get("error", "Workflow did not complete.")


async def _set(session, job, *, status, progress, current_step):
    job.status = status
    job.progress = progress
    job.current_step = current_step
    job.updated_at = datetime.utcnow()
    await session.commit()


async def _fail(session, job, code, message):
    job.status = "failed"
    job.error_code = code
    job.error_message = message
    job.updated_at = datetime.utcnow()
    await session.commit()
