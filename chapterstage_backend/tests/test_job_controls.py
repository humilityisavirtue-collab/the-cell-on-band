"""Job controls gate: cancellation, retry, heartbeat, and Band room URL."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import func, select

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

_TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///%s/test.db" % _TMP.name
os.environ["GENERATED_SITE_ROOT"] = _TMP.name + "/static"
os.environ["BAND_TRANSPORT_MODE"] = "test"
os.environ["BAND_ROOM_URL_TEMPLATE"] = "https://band.test/rooms/{room_id}"
os.environ["CHAPTERSTAGE_ENV_FILE"] = _TMP.name + "/missing.env"
for _key in ("LLM_PROVIDER", "OLLAMA_MODEL", "OLLAMA_BASE_URL"):
    os.environ.pop(_key, None)

from fastapi.testclient import TestClient  # noqa: E402
from app.database import async_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Experience, GenerationJob, _now  # noqa: E402
from app.schemas import JobCreateRequest  # noqa: E402
from app.services import job_service, sse_bus  # noqa: E402

FAILURES: list[str] = []
RAN: list[str] = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


async def _create_job(
        chapter_id: str,
        audience_level: str = "intermediate",
        experience_style: str = "quiz_first",
        target_screen_count: int = 4,
        enable_auto_brainstorm: bool = False) -> GenerationJob:
    async with async_session() as session:
        return await job_service.create_job(session, JobCreateRequest(
            chapter_id=chapter_id,
            audience_level=audience_level,
            experience_style=experience_style,
            target_screen_count=target_screen_count,
            enable_auto_brainstorm=enable_auto_brainstorm,
        ))


async def _set_job_fields(job_id: str, **fields) -> GenerationJob:
    async with async_session() as session:
        job = await session.get(GenerationJob, job_id)
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = _now()
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job


async def _get_job(job_id: str) -> GenerationJob:
    async with async_session() as session:
        return await session.get(GenerationJob, job_id)


async def _experience_count(job_id: str) -> int:
    async with async_session() as session:
        return (await session.execute(
            select(func.count(Experience.id)).where(
                Experience.job_id == job_id))).scalar_one()


async def _next_heartbeat(job_id: str) -> dict:
    sse_bus.clear(job_id)
    stream = sse_bus.stream(job_id, heartbeat_seconds=0.01)
    try:
        return await asyncio.wait_for(stream.__anext__(), timeout=1.0)
    finally:
        await stream.aclose()


def _chapter_id(c: TestClient) -> str:
    good_text = "Cells convert stored energy into useful work. " * 40
    r = c.post("/api/v1/chapters/text",
               json={"book_title": "Bio", "chapter_title": "Cells",
                     "text": good_text})
    check("POST /chapters/text valid for job controls",
          r.status_code == 201 and "chapter_id" in r.json(), receipt=r.text)
    return r.json()["chapter_id"]


def main():
    print("test_job_controls.py — cancellation + retry + heartbeat")
    with TestClient(app) as c:
        chapter_id = _chapter_id(c)

        queued_job = asyncio.run(_create_job(chapter_id))
        r = c.post("/api/v1/generation-jobs/%s/cancel" % queued_job.id)
        cancelled = r.json()
        check("cancel queued job -> terminal cancelled",
              r.status_code == 200
              and cancelled["status"] == "cancelled"
              and cancelled["current_step"] == "Cancelled",
              receipt=r.text)
        check("cancelled queued job does not publish an experience",
              cancelled["experience_id"] is None
              and cancelled["public_url"] is None
              and asyncio.run(_experience_count(queued_job.id)) == 0,
              receipt=cancelled)

        with c.stream("GET",
                      "/api/v1/generation-jobs/%s/events" % queued_job.id) as s:
            body = "".join(s.iter_text())
        check("cancelled job SSE stream ends with job_cancelled",
              "event: job_cancelled" in body, receipt=body[:500])

        r = c.post("/api/v1/generation-jobs/%s/cancel" % queued_job.id)
        check("cancel already cancelled job is idempotent",
              r.status_code == 200 and r.json()["status"] == "cancelled",
              receipt=r.text)

        active_job = asyncio.run(_create_job(chapter_id))
        asyncio.run(_set_job_fields(
            active_job.id, status="extracting", progress=0.10,
            current_step="Preparing chapter text."))
        r = c.post("/api/v1/generation-jobs/%s/cancel" % active_job.id)
        check("cancel active job marks cancelling",
              r.status_code == 200 and r.json()["status"] == "cancelling",
              receipt=r.text)

        r = c.post("/api/v1/generation-jobs/%s/retry" % active_job.id)
        check("retry non-terminal job -> 409 JOB_ALREADY_RUNNING",
              r.status_code == 409
              and r.json()["error"]["code"] == "JOB_ALREADY_RUNNING",
              receipt=r.text)

        completed_job = asyncio.run(_create_job(chapter_id))
        asyncio.run(_set_job_fields(
            completed_job.id, status="completed", progress=1.0,
            current_step="Completed", completed_at=_now()))
        r = c.post("/api/v1/generation-jobs/%s/cancel" % completed_job.id)
        check("cancel completed job -> 409 JOB_ALREADY_RUNNING",
              r.status_code == 409
              and r.json()["error"]["code"] == "JOB_ALREADY_RUNNING",
              receipt=r.text)

        failed_job = asyncio.run(_create_job(chapter_id))
        asyncio.run(_set_job_fields(
            failed_job.id, status="failed_agent_workflow",
            current_step="Failed", completed_at=_now()))
        r = c.post("/api/v1/generation-jobs/%s/cancel" % failed_job.id)
        check("cancel failed job -> 409 JOB_ALREADY_RUNNING",
              r.status_code == 409
              and r.json()["error"]["code"] == "JOB_ALREADY_RUNNING",
              receipt=r.text)
        for source_job, label in (
                (queued_job, "cancelled"),
                (completed_job, "completed"),
                (failed_job, "failed")):
            r = c.post("/api/v1/generation-jobs/%s/retry" % source_job.id)
            check("retry %s job -> new accepted job" % label,
                  r.status_code == 202
                  and r.json()["status"] == "queued"
                  and r.json()["job_id"] != source_job.id
                  and r.json()["status_url"]
                  and r.json()["events_url"],
                  receipt=r.text)
            if label == "cancelled":
                retried = asyncio.run(_get_job(r.json()["job_id"]))
                check("retry copies original generation settings",
                      retried.chapter_id == queued_job.chapter_id
                      and retried.audience_level == queued_job.audience_level
                      and retried.experience_style == queued_job.experience_style
                      and retried.target_screen_count
                      == queued_job.target_screen_count
                      and retried.enable_auto_brainstorm
                      == queued_job.enable_auto_brainstorm,
                      receipt=vars(retried))

        room_job = asyncio.run(_create_job(chapter_id))
        asyncio.run(_set_job_fields(room_job.id, band_room_id="room-123"))
        r = c.get("/api/v1/generation-jobs/%s" % room_job.id)
        check("status includes configured Band room URL",
              r.status_code == 200
              and r.json()["band_room_url"]
              == "https://band.test/rooms/room-123",
              receipt=r.text)
        r = c.get("/api/v1/generation-jobs/%s/trace" % room_job.id)
        check("trace includes configured Band room URL",
              r.status_code == 200
              and r.json()["band_room_url"]
              == "https://band.test/rooms/room-123",
              receipt=r.text)

        heartbeat = asyncio.run(_next_heartbeat("idle-job"))
        heartbeat_data = json.loads(heartbeat["data"])
        check("idle SSE stream emits heartbeat without stored events",
              heartbeat["event"] == "heartbeat"
              and heartbeat_data["job_id"] == "idle-job",
              receipt=heartbeat)

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — job controls expose cancellation, retry, heartbeat, "
          "and optional Band room URL contracts.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
