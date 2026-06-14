"""test_chapter_graph.py — M3 gate: stubbed graph reaches `completed`, and EVERY
inter-agent handoff rides band_service (the invariant), asserted mechanically.

Per the spec's verification-debt note, the gate carries a negative control that
mirrors the REAL failure: sever Band mid-job -> the job MUST stall (no
`completed`). A green that cannot go red is theater. Exit nonzero on any failure.

Run: py -3.12 apps/band/chapterstage_backend/tests/test_chapter_graph.py
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


def run(band):
    return chapter_graph.ChapterWorkflow(band).run("job-m3", "Young Wizards ch.1")


def main():
    print("test_chapter_graph.py — M3 gate (stubbed graph + invariant)")

    # -- POSCONTROL: live room -> completed with a valid module.
    band = BandService()
    state = run(band)
    check("POSCONTROL stubbed graph reaches completed with Band alive",
          state["status"] == "completed",
          receipt="status=%r log=%r" % (state["status"], state.get("log")))
    check("POSCONTROL all 4 stages ran (structure->brainstorm->visual->verifier)",
          state.get("log") == ["structure", "brainstorm", "visual", "verifier"],
          receipt="log=%r" % state.get("log"))
    check("POSCONTROL a published module envelope exists (kind=module)",
          isinstance(state.get("module"), dict)
          and state["module"].get("kind") == "module",
          receipt="module=%r" % state.get("module"))

    # -- MECHANICAL invariant: every transition went THROUGH band_service.
    check("INVARIANT every inter-agent hop rode band_service (4 handoffs recorded)",
          len(band.handoffs) == 4,
          receipt="handoffs=%r" % band.handoffs)
    check("INVARIANT all roles were recruited into the room",
          band.recruited == ["structure", "brainstorm", "visual", "verifier"],
          receipt="recruited=%r" % band.recruited)

    # -- NEGATIVE CONTROL (the real failure): sever the room BEFORE any handoff.
    band = BandService()
    band.sever()
    state = run(band)
    check("NEGCONTROL Band severed at start -> job STALLS, never completed",
          state["status"] == "stalled" and state["status"] != "completed",
          receipt="status=%r" % state["status"])
    check("NEGCONTROL severed run published NO module (no completed result)",
          state.get("module") is None,
          receipt="module=%r" % state.get("module"))
    check("NEGCONTROL the handoff was actually dropped (sever is real)",
          len(band.dropped) >= 1 and len(band.handoffs) == 0,
          receipt="dropped=%r handoffs=%r" % (band.dropped, band.handoffs))

    # -- NEGATIVE CONTROL 2: sever MID-job (after structure's handoff lands).
    band = BandService()
    state = chapter_graph.ChapterWorkflow(band)
    # let structure's handoff land, then sever before brainstorm's outbound hop
    wf = chapter_graph.ChapterWorkflow(band)
    orig_handoff = band.handoff
    calls = {"n": 0}

    def severing_handoff(frm, to, env):
        calls["n"] += 1
        if calls["n"] == 2:           # drop brainstorm->visual
            band.sever()
        return orig_handoff(frm, to, env)

    band.handoff = severing_handoff
    state = wf.run("job-m3b", "ch.1")
    check("NEGCONTROL2 sever mid-job -> stalled, not completed",
          state["status"] == "stalled",
          receipt="status=%r log=%r" % (state["status"], state.get("log")))
    check("NEGCONTROL2 stalled job has no module (verifier never reached)",
          state.get("module") is None,
          receipt="module=%r" % state.get("module"))

    # -- DISCRIMINATOR: live completes, severed stalls — the gate can tell them apart.
    live = run(BandService())
    sev = BandService(); sev.sever()
    dead = run(sev)
    check("DISCRIMINATOR live=completed while severed=stalled (gate not theater)",
          live["status"] == "completed" and dead["status"] == "stalled",
          receipt="live=%r dead=%r" % (live["status"], dead["status"]))

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — M3 stubbed graph reaches completed, every handoff rides "
          "band_service, and severing Band stalls the job. Invariant holds.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
