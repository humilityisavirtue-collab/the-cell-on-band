"""In-memory SSE event bus for MVP job progress."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime

HEARTBEAT_SECONDS = 15.0
TERMINAL_EVENTS = {"experience_ready", "job_failed", "job_cancelled"}
logger = logging.getLogger(__name__)

_events: dict[str, list[dict]] = defaultdict(list)
_conditions: dict[str, asyncio.Condition] = {}


def _condition(job_id: str) -> asyncio.Condition:
    if job_id not in _conditions:
        _conditions[job_id] = asyncio.Condition()
    return _conditions[job_id]


async def publish(job_id: str, event: str, data: dict) -> None:
    payload = dict(data)
    payload.setdefault("job_id", job_id)
    payload.setdefault("created_at", datetime.utcnow().isoformat() + "Z")
    record = {"event": event, "data": payload}
    cond = _condition(job_id)
    async with cond:
        _events[job_id].append(record)
        cond.notify_all()
    logger.info("sse event published job_id=%s event=%s", job_id, event)


async def stream(job_id: str, heartbeat_seconds: float = HEARTBEAT_SECONDS):
    cond = _condition(job_id)
    index = 0
    while True:
        record = None
        async with cond:
            if index >= len(_events[job_id]):
                try:
                    await asyncio.wait_for(cond.wait(), timeout=heartbeat_seconds)
                except asyncio.TimeoutError:
                    record = {"event": "heartbeat", "data": {
                        "job_id": job_id,
                        "created_at": datetime.utcnow().isoformat() + "Z",
                    }}
            if record is None and index < len(_events[job_id]):
                record = _events[job_id][index]
                index += 1
        if record is None:
            continue
        yield {"event": record["event"], "data": json.dumps(record["data"])}
        if record["event"] in TERMINAL_EVENTS:
            break


def clear(job_id: str) -> None:
    _events.pop(job_id, None)
