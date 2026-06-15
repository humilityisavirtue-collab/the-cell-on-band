"""sse_bus.py — in-memory per-job event bus for SSE progress (handoff §9.6, M2).

The generation runner publishes job_progress / agent_message / experience_ready /
job_failed events; the /events endpoint subscribes and streams them as
text/event-stream. MVP-scale: in-process, no Redis. Two realities it handles:

  - The runner executes the sync workflow in a WORKER THREAD (asyncio.to_thread),
    so publish() is thread-safe — it hops each event onto the main loop with
    call_soon_threadsafe before touching the asyncio.Queues.
  - A client may subscribe AFTER some events fired; each new subscriber is
    replayed the job's history first, so the frontend never misses a step.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict


class JobEventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._history: dict[str, list[dict]] = defaultdict(list)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ---- publish (callable from any thread) ----
    def publish(self, job_id: str, event_type: str, data: dict) -> None:
        event = {"event": event_type, "data": data}
        self._history[job_id].append(event)
        loop = self._loop
        if loop is None or not self._subs.get(job_id):
            return
        for q in list(self._subs[job_id]):
            loop.call_soon_threadsafe(q.put_nowait, event)

    def mark_done(self, job_id: str) -> None:
        """Sentinel so open SSE streams can close cleanly."""
        self.publish(job_id, "_eos", {})

    # ---- subscribe (async, main loop) ----
    async def subscribe(self, job_id: str):
        """Yield events for a job: history first, then live until _eos."""
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        # replay history, then attach so no event is lost between the two
        for event in list(self._history[job_id]):
            await q.put(event)
        self._subs[job_id].add(q)
        try:
            while True:
                event = await q.get()
                if event["event"] == "_eos":
                    break
                yield event
        finally:
            self._subs[job_id].discard(q)


# module-level singleton the app + runner share
bus = JobEventBus()
