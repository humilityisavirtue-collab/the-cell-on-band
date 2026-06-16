"""In-memory SSE event bus for MVP job progress."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime

TERMINAL_EVENTS = {"experience_ready", "job_failed"}
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


async def stream(job_id: str):
    cond = _condition(job_id)
    index = 0
    while True:
        async with cond:
            while index >= len(_events[job_id]):
                await cond.wait()
            record = _events[job_id][index]
            index += 1
        yield {"event": record["event"], "data": json.dumps(record["data"])}
        if record["event"] in TERMINAL_EVENTS:
            break


def clear(job_id: str) -> None:
    _events.pop(job_id, None)
