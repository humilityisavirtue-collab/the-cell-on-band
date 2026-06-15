"""live_progress.py — tiny thread-safe registry of in-flight job progress.

The generation runner executes the workflow in a worker thread; its per-stage
callback updates this registry. GET /generation-jobs/{id} overlays it onto the DB
row so a polling client sees live status/progress without the runner having to
write the DB from inside the worker thread. Cleared when the job reaches a
terminal state. Single-writes under the GIL are atomic enough for MVP scale.
"""
from __future__ import annotations

_live: dict[str, dict] = {}


def update(job_id: str, status: str, progress: float, current_step: str) -> None:
    _live[job_id] = {"status": status, "progress": progress,
                     "current_step": current_step}


def get(job_id: str) -> dict | None:
    return _live.get(job_id)


def clear(job_id: str) -> None:
    _live.pop(job_id, None)
