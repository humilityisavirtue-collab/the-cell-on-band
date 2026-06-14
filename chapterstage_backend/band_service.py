"""band_service.py — the ONLY inter-agent channel in the ChapterStage backend.

THE INVARIANT (CHAPTERSTAGE_BACKEND_SPEC.md §THE INVARIANT, gated): agent-to-agent
handoffs ride Band @mentions. LangGraph is per-agent internal logic only; no node
calls another agent directly. This module is that single seam — every handoff in
the workflow goes through BandService.handoff(), nothing else. M4 wires this to the
real band_agent.BandTransport (@mention via thenvoi_send_message); until then it is
an in-memory room with a sever() switch so the kill test is deterministic offline.

If a node ever reaches the next node WITHOUT calling handoff() here, the invariant
is broken and the load-bearing gate must catch it. sever() == WS drop / key revoke:
after it, handoff() DROPS the message and returns False, so the workflow stalls.
"""
from __future__ import annotations


class BandService:
    """The Band room as the live coordination layer (not a log). Records every
    handoff so the gate can assert mechanically that routing went through here.

    M4 (the invariant milestone): an optional `transport` plugs the real Band
    @mention path under handoff(). The production transport is
    band_agent.BandTransport — its connect()/post() are the kickoff seam (raise
    NotImplementedError until the band-sdk docs land), so this stays offline-
    deterministic now and goes live unchanged at kickoff. The transport must
    expose `.post(to_role, text) -> bool` and an `.alive` flag (sever == WS drop).
    With no transport, the in-memory room is the deterministic offline twin used
    by the load-bearing gate.
    """

    def __init__(self, transport=None):
        self.transport = transport
        self.alive = True
        self.handoffs: list[dict] = []      # delivered (from, to, kind)
        self.dropped: list[dict] = []       # dropped-after-sever
        self.recruited: list[str] = []      # roles invited to the room

    # --- room lifecycle (M4 fills these against the real transport) ---
    def open_room(self, job_id: str) -> str:
        self.room_id = "room-%s" % job_id
        if self.transport is not None and hasattr(self.transport, "open_room"):
            self.transport.open_room(self.room_id)
        return self.room_id

    def recruit(self, role: str) -> None:
        self.recruited.append(role)
        if self.transport is not None and hasattr(self.transport, "recruit"):
            self.transport.recruit(role)

    def _transport_alive(self) -> bool:
        # severance is whichever side dropped: the service or the live transport
        if self.transport is not None:
            return self.alive and getattr(self.transport, "alive", True)
        return self.alive

    # --- the single inter-agent channel ---
    def handoff(self, from_role: str, to_role: str, envelope: dict) -> bool:
        """Pass an agent's output to the next role via the room (an @mention over
        the transport when wired). Returns False if the room is severed — the
        next agent is then NEVER triggered (the stall)."""
        rec = {"from": from_role, "to": to_role, "kind": envelope.get("kind", "?")}
        if not self._transport_alive():
            self.dropped.append(rec)
            return False
        if self.transport is not None:
            # the real @mention: render the envelope to the next role in the room
            text = "@%s\n%s" % (to_role, _render(envelope))
            delivered = bool(self.transport.post(to_role, text))
            if not delivered:
                self.dropped.append(rec)
                return False
        self.handoffs.append(rec)
        return True

    def sever(self) -> None:
        self.alive = False
        if self.transport is not None and hasattr(self.transport, "sever"):
            self.transport.sever()


def _render(envelope: dict) -> str:
    """Render an envelope for an @mention. Reuses chapterstage_envelopes.render
    (shared Band transport format) when importable; falls back to json."""
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import chapterstage_envelopes as cse
        return cse.render(envelope)
    except Exception:
        import json
        return json.dumps(envelope)
