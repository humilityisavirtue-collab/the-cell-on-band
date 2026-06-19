"""test_m4_band_loadbearing.py — M4 gate: the load-bearing kill test run against
the REAL ChapterWorkflow, with handoffs routed over a Band TRANSPORT (the @mention
path), not just the in-memory room.

CHAPTERSTAGE_BACKEND_SPEC.md §M4: "gate_langgraph_loadbearing.py extended/run
against the live graph — sever Band mid-job → job stalls, no completed." This is
that gate, productionized: band_service wraps a transport; severing the transport
(the offline twin of the live WS drop) must stall the real workflow.

The production transport is band_agent.BandTransport (its connect()/post() are the
kickoff seam). MockTransport here is its deterministic offline twin — same contract
(.post / .alive / .sever), so the gate is real today and the live run is identical
at kickoff. Negative controls mirror the REAL failure (Band down). Exit nonzero on
any failure.

Run: py -3.12 apps/band/chapterstage_backend/tests/test_m4_band_loadbearing.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "workflows"))

from band_service import BandService          # noqa: E402
import chapter_graph                          # noqa: E402

FAILURES: list[str] = []
RAN: list[str] = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


class MockTransport:
    """Deterministic offline twin of band_agent.BandTransport. Same contract the
    real WS transport exposes: post() delivers an @mention into the room; sever()
    is the WS drop / key revoke; after it, post() returns False."""

    def __init__(self):
        self.alive = True
        self.posts: list[tuple[str, str]] = []   # (to_role, text)
        self.rooms: list[str] = []
        self.recruited: list[str] = []

    def open_room(self, room_id): self.rooms.append(room_id)
    def recruit(self, role): self.recruited.append(role)

    def post(self, to_role, text) -> bool:
        if not self.alive:
            return False
        self.posts.append((to_role, text))
        return True

    def sever(self): self.alive = False


def run(transport):
    band = BandService(transport=transport)
    state = chapter_graph.ChapterWorkflow(band).run("job-m4", "Young Wizards ch.2")
    return band, state


def main():
    print("test_m4_band_loadbearing.py — M4 gate (load-bearing over the transport)")

    # -- POSCONTROL: live transport -> real workflow completes.
    tx = MockTransport()
    band, state = run(tx)
    check("POSCONTROL real workflow completes over a live transport",
          state["status"] == "completed",
          receipt="status=%r log=%r" % (state["status"], state.get("log")))
    check("POSCONTROL published module is valid (kind=module)",
          isinstance(state.get("module"), dict)
          and state["module"].get("kind") == "module")

    # -- MECHANICAL: every handoff actually went over the transport @mention path.
    check("every inter-agent handoff rode the transport (3 posts)",
          len(tx.posts) == 3, receipt="posts=%d" % len(tx.posts))
    check("transport handoffs are real @mentions to actual agents",
          all(to != "room" and text.startswith("@%s" % to) and "kind" in text
              for to, text in tx.posts),
          receipt="posts=%r" % [(to, t[:20]) for to, t in tx.posts])

    # -- NEGATIVE CONTROL (the real failure: Band/transport down at start).
    tx = MockTransport(); tx.sever()
    band, state = run(tx)
    check("NEGCONTROL transport severed at start -> job STALLS (not completed)",
          state["status"] == "stalled",
          receipt="status=%r" % state["status"])
    check("NEGCONTROL severed transport published NO module",
          state.get("module") is None)
    check("NEGCONTROL nothing posted over the dead transport",
          tx.posts == [] and len(band.dropped) >= 1,
          receipt="posts=%r dropped=%r" % (tx.posts, band.dropped))

    # -- NEGATIVE CONTROL 2: sever the transport MID-job.
    tx = MockTransport()
    band = BandService(transport=tx)
    wf = chapter_graph.ChapterWorkflow(band)
    orig_post = tx.post
    calls = {"n": 0}

    def severing_post(to, text):
        calls["n"] += 1
        if calls["n"] == 2:           # drop the brainstorm->visual @mention
            tx.sever()
        return orig_post(to, text)

    tx.post = severing_post
    state = wf.run("job-m4b", "ch.2")
    check("NEGCONTROL2 transport severed mid-job -> stalled, no module",
          state["status"] == "stalled" and state.get("module") is None,
          receipt="status=%r log=%r" % (state["status"], state.get("log")))

    # -- DISCRIMINATOR: live transport completes, severed stalls (gate not theater).
    live_tx = MockTransport()
    _, live = run(live_tx)
    dead_tx = MockTransport(); dead_tx.sever()
    _, dead = run(dead_tx)
    check("DISCRIMINATOR live transport=completed vs severed=stalled",
          live["status"] == "completed" and dead["status"] == "stalled",
          receipt="live=%r dead=%r" % (live["status"], dead["status"]))

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — M4: the real ChapterWorkflow is load-bearing over the Band "
          "transport. Severing the @mention path stalls the job (no completed, no "
          "module). The invariant holds on the real code, not a toy graph.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
