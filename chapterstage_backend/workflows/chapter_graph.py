"""chapter_graph.py — ORCHESTRATION via Band @mentions (the invariant milestone).

CHAPTERSTAGE_BACKEND_SPEC.md §THE INVARIANT: no top-level graph may call another
agent directly. This driver runs each agent's per-agent graph (nodes.py), then
hands the output to the next role THROUGH band_service — the only inter-agent
channel. Sever band_service mid-job and the chain stalls before `completed`: that
is the whole-backend acceptance test.

This is the productionized GOOD topology that gate_langgraph_loadbearing.py proved
load-bearing. M4 swaps band_service's in-memory room for the live BandTransport;
the orchestration logic here does not change.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chapter_nodes as nodes  # noqa: E402  (STAGES + per-agent nodes)

_BAND = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_BAND))
import chapterstage_envelopes as cse  # noqa: E402

logger = logging.getLogger(__name__)


class ChapterWorkflow:
    """Drives the artifact chain through band_service. Returns the final state;
    status == 'completed' ONLY if the module landed via a live room."""

    def __init__(self, band_service=None):
        if band_service is None:
            from app.services.band_transport.factory import create_band_service
            band_service = create_band_service()
        self.band = band_service

    def run(
            self, job_id: str, source_ref: str, source_text: str = "",
            audience_level: str = "beginner", experience_style: str = "visual_story",
            target_screen_count: int | None = None) -> dict:
        self.band.open_room(job_id)
        for role, _slot, _fn, _to in nodes.STAGES:
            self.band.recruit(role)

        state: dict = {"job_id": job_id, "source_ref": source_ref,
                       "source_text": source_text,
                       "audience_level": audience_level,
                       "experience_style": experience_style,
                       "target_screen_count": target_screen_count,
                       "status": "running", "log": []}

        for role, slot, node_fn, to_role in nodes.STAGES:
            try:
                env = node_fn(state)             # the agent's own graph runs + emits
            except Exception as exc:
                logger.exception("chapter agent failed role=%s job_id=%s",
                                 role, job_id)
                state["status"] = "failed"
                state["error_stage"] = role
                state["error_type"] = exc.__class__.__name__
                state["error"] = str(exc)
                return state
            problems = cse.validate(env)         # node output validated by the contract
            if problems:
                state["status"] = "failed"
                state["error"] = "%s emitted invalid %s: %s" % (
                    role, env.get("kind"), "; ".join(problems))
                return state
            state[slot] = env
            state["log"].append(role)
            # THE INVARIANT: each inter-agent handoff rides band_service. The
            # verifier's module is terminal, so it is not @mentioned to a fake
            # "room" participant.
            if to_role is not None and not self.band.handoff(role, to_role, env):
                state["status"] = "stalled"
                state["error_stage"] = role
                state["error"] = "Band handoff failed from %s to %s." % (
                    role, to_role)
                transport = getattr(self.band, "transport", None)
                last_error = getattr(transport, "last_error", None)
                if last_error:
                    state["transport_error"] = last_error
                return state

        # completed ONLY if we got here: every real inter-agent handoff landed and
        # the verifier emitted a valid module.
        state["status"] = "completed"
        return state
