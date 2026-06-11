"""Club's gate: "Band removable = FAIL" — the load-bearing kill test.

Spec: cell/specs/BAND_OF_AGENTS_SPEC.md (gate section). Owner: Club.
Authored BEFORE any agent is wired, per spec. Runs fully offline through
the BandCellAgent.receive() seam — no SDK, no network, no real bus writes
(band_agent.ARCHIVE is redirected to a temp dir for the whole run).

Four legs, all can-fail:
  1. KILL TEST   — drive a full loop to done with Band alive (positive
                   control), then sever Band mid-flight and prove the loop
                   STALLS: no done envelope by any path, nucleus refuses.
  2. NEGCONTROL  — malformed envelopes (artifact w/o ref, verdict w/o
                   receipts) MUST be rejected by the receiver.
  3. CONSUME-PATH— mechanical source scan: no loop module reads any
                   cell/bus/*.jsonl; the only bus touch is the append-only
                   archive mirror.
  4. DECOY SWEEP — gate-of-the-gate: kill validate()/reject()/classifier
                   in-process and confirm the corresponding checks go RED.
                   A gate that can't catch a dead organ is theater.

Exit 0 = GATE PASS. Exit 1 = FAIL (receipts printed).

Offline:  py -3.12 apps/band/gate_band_loadbearing.py
Live leg (post-kickoff, echo agent): the 60-second WS-drop timing run —
this harness's sever() is the deterministic offline twin of that test.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import band_agent  # noqa: E402
import consent     # noqa: E402
import envelopes   # noqa: E402

# Never let gate traffic touch the real archive (learned 2026-06-11: an
# earlier selftest wrote 7 test records into the submission transcript).
_TMP = tempfile.TemporaryDirectory()
band_agent.ARCHIVE = Path(_TMP.name) / "band_archive.jsonl"

FAILURES = []
RAN = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


# ------------------------------------------------------- mock Band transport

class MockBand:
    """In-memory stand-in for the Band room. sever() = WS drop / key revoke.
    After sever, every post is DROPPED — exactly what the live kill test
    does with the real transport."""

    def __init__(self):
        self.alive = True
        self.delivered = []   # (sender, to, kind)
        self.dropped = []     # (sender, to, kind)

    def sever(self):
        self.alive = False

    def post(self, sender, to_role, env):
        kind = env.get("kind", "?")
        if not self.alive:
            self.dropped.append((sender, to_role, kind))
            return False
        self.delivered.append((sender, to_role, kind))
        return True


def fresh_agents():
    return {r: band_agent.BandCellAgent(r) for r in band_agent.LOOP_ROLES}


def pump(agents, band, outbox):
    """Deliver queued (sender, to, env, prose) posts; route replies until
    quiet. Returns list of done envelopes that reached the room."""
    done_seen = []
    guard = 0
    while outbox and guard < 100:
        guard += 1
        sender, to, env, prose = outbox.pop(0)
        if not band.post(sender, to, env):
            continue  # Band is down: the message does not exist
        if env.get("kind") == "done":
            done_seen.append(env)
        if to not in agents:
            continue  # 'room' etc. — no agent to wake
        for t2, e2, p2 in agents[to].receive(envelopes.render(env, prose), sender):
            outbox.append((to, t2, e2, p2))
    return done_seen


def drive_loop(band, sever_after=None):
    """Drive one full loop, simulating each role's LLM turn explicitly.
    sever_after: None | 'spec' | 'artifact' — when Band goes down."""
    agents = fresh_agents()
    outbox = []

    # gamer's turn: decompose ask -> spec @diamond
    for to, env, prose in agents["gamer"].behavior.plan(
            "band-g1", "ship a hello tool", "write hello.py, test it, commit"):
        outbox.append(("gamer", to, env, prose))
    done = pump(agents, band, outbox)
    if sever_after == "spec":
        band.sever()

    # diamond's turn: build lands -> artifact @club
    for to, env, prose in agents["diamond"].behavior.post_artifact(
            "band-g1", "https://github.com/x/band-demo", "abc1234", "hello.py"):
        outbox.append(("diamond", to, env, prose))
    done += pump(agents, band, outbox)
    if sever_after == "artifact":
        band.sever()

    # club's turn: gate ran -> verdict @nucleus
    for to, env, prose in agents["club"].behavior.post_verdict(
            "band-g1", "kill-test", "PASS", "$ selftest\nall green"):
        outbox.append(("club", to, env, prose))
    done += pump(agents, band, outbox)
    return agents, done


def leg1_kill_test():
    print("LEG 1 — kill test (Band removable = FAIL)")

    # Positive control: with Band ALIVE the loop must complete. A stall
    # result means nothing if the harness can't drive a loop to done.
    band = MockBand()
    agents, done = drive_loop(band, sever_after=None)
    check("POSCONTROL loop completes with Band alive (done emitted)",
          len(done) == 1 and done[0]["verdict"]["result"] == "PASS",
          receipt="done_seen=%d delivered=%s" % (len(done), band.delivered))

    # Kill: sever right after the spec lands. Artifact, verdict, done must
    # all fail to propagate; nucleus must refuse to close.
    band = MockBand()
    agents, done = drive_loop(band, sever_after="spec")
    refused = False
    try:
        agents["nucleus"].behavior.emit_done("band-g1")
    except PermissionError:
        refused = True
    check("severed-after-spec: NO done envelope by any path",
          done == [], receipt="done=%r" % done)
    check("severed-after-spec: messages actually dropped (sever is real)",
          len(band.dropped) >= 1, receipt="dropped=%r" % band.dropped)
    check("severed-after-spec: nucleus REFUSES manual done (no verdict)",
          refused)

    # Kill later: sever after the artifact landed at club. The verdict can
    # never reach nucleus -> still no done.
    band = MockBand()
    agents, done = drive_loop(band, sever_after="artifact")
    refused = False
    try:
        agents["nucleus"].behavior.emit_done("band-g1")
    except PermissionError:
        refused = True
    check("severed-after-artifact: NO done envelope", done == [],
          receipt="done=%r dropped=%r" % (done, band.dropped))
    check("severed-after-artifact: nucleus still refuses", refused)


def leg2_negative_controls():
    print("LEG 2 — negative controls (validation is not theater)")
    agents = fresh_agents()

    # Real failure mode: an LLM posts an artifact with no checkout ref.
    bad_artifact = envelopes.render({
        "kind": "artifact", "task_id": "band-g2", "from": "diamond",
        "to": "club", "artifact": {"repo": "https://github.com/x/y"}})
    replies = agents["club"].receive(bad_artifact, "diamond")
    check("artifact w/o ref -> club REJECTS with FAIL verdict",
          len(replies) == 1 and replies[0][1]["verdict"]["result"] == "FAIL")

    # Real failure mode: a verdict that asserts instead of showing receipts.
    bad_verdict = envelopes.render({
        "kind": "verdict", "task_id": "band-g2", "from": "club",
        "to": "nucleus", "verdict": {"gate": "g", "result": "PASS",
                                     "receipts": ""}})
    replies = agents["nucleus"].receive(bad_verdict, "club")
    check("verdict w/o receipts -> nucleus REJECTS",
          len(replies) == 1 and replies[0][1]["verdict"]["result"] == "FAIL")

    # And the mirror: well-formed versions of BOTH must not be rejected.
    good_artifact = envelopes.render(envelopes.make_envelope(
        "artifact", "band-g2", "diamond", "club",
        artifact={"repo": "https://github.com/x/y", "ref": "abc", "path": "p"}))
    check("well-formed artifact is NOT rejected",
          agents["club"].receive(good_artifact, "diamond") == [])


def leg3_consume_path():
    print("LEG 3 — consume-path inspection (Band is transport, not mirror)")
    loop_modules = ["envelopes.py", "consent.py", "band_agent.py", "run_pod.py"]
    bus_re = re.compile(r"cell[/\\]+bus", re.IGNORECASE)
    offenders = []
    archive_append_ok = False
    for name in loop_modules:
        src = (_HERE / name).read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(src.splitlines(), 1):
            if not bus_re.search(line):
                continue
            stripped = line.strip()
            if stripped.startswith("#") or '"""' in stripped:
                continue  # prose/docstring mention, not code
            if "band_archive.jsonl" in line:
                continue  # the sanctioned archive path constant
            offenders.append("%s:%d: %s" % (name, i, stripped))
        if name == "band_agent.py":
            archive_append_ok = bool(
                re.search(r"open\(\s*ARCHIVE\s*,\s*[\"']a[\"']", src))
    check("no loop module touches cell/bus/ outside the archive constant",
          offenders == [], receipt="; ".join(offenders))
    check("archive mirror opens append-only ('a')", archive_append_ok)
    # Behavioral proof on top of the source scan: a full loop run must not
    # create or read any role bus file (ARCHIVE already redirected to temp).
    real_bus = Path("C:/kit.triv/cell/bus/band_archive.jsonl")
    band = MockBand()
    drive_loop(band, sever_after=None)
    check("full loop run leaves no real band_archive.jsonl behind",
          not real_bus.exists())


def leg4_decoy_sweep():
    print("LEG 4 — decoy sweep (the gate itself can go red)")

    # Decoy A: dead validator -> leg-2-style rejection must vanish.
    orig_validate = envelopes.validate
    envelopes.validate = lambda env: []
    try:
        agents = fresh_agents()
        bad = envelopes.render({
            "kind": "artifact", "task_id": "band-g4", "from": "diamond",
            "to": "club", "artifact": {"repo": "r"}})
        leaked = agents["club"].receive(bad, "diamond") == []
    finally:
        envelopes.validate = orig_validate
    check("DECOY dead validate(): bad artifact sails through (gate would catch)",
          leaked)

    # Decoy B: dead reject() -> REJECT path must vanish.
    orig_reject = band_agent.RoleBehavior.reject
    band_agent.RoleBehavior.reject = lambda self, env, problems: []
    try:
        agents = fresh_agents()
        bad = envelopes.render({
            "kind": "artifact", "task_id": "band-g4", "from": "diamond",
            "to": "club", "artifact": {"repo": "r"}})
        leaked = agents["club"].receive(bad, "diamond") == []
    finally:
        band_agent.RoleBehavior.reject = orig_reject
    check("DECOY dead reject(): rejection disappears (gate would catch)",
          leaked)

    # Decoy C: dead consent classifier -> unsafe action stops blocking.
    orig_rc = consent.requires_consent
    consent.requires_consent = lambda kind, target: False
    try:
        agents = fresh_agents()
        posts, allowed = agents["diamond"].behavior.guard_action(
            "band-g4", "net_push", "github.com/public")
        leaked = allowed and posts == []
    finally:
        consent.requires_consent = orig_rc
    check("DECOY dead consent classifier: net_push no longer blocks (gate would catch)",
          leaked)

    # After restores, the real organs must work again (no decoy residue).
    agents = fresh_agents()
    bad = envelopes.render({
        "kind": "artifact", "task_id": "band-g4", "from": "diamond",
        "to": "club", "artifact": {"repo": "r"}})
    rejected = agents["club"].receive(bad, "diamond")
    posts, allowed = agents["diamond"].behavior.guard_action(
        "band-g4", "net_push", "github.com/public")
    check("decoys restored: rejection and consent block both live again",
          len(rejected) == 1 and not allowed)


def main():
    print("gate_band_loadbearing.py — Club's kill-test gate (offline)")
    leg1_kill_test()
    leg2_negative_controls()
    leg3_consume_path()
    leg4_decoy_sweep()
    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — Band is load-bearing in this build, validation is "
          "real, consume path is Band-only, and the gate can go red.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
