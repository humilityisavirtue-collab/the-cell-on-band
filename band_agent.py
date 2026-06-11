"""Generic Band agent wrapper for the K-Cell 4-agent loop.

Spec: cell/specs/BAND_OF_AGENTS_SPEC.md (supersedes the 8-role mapping in
this directory's older README).

    Planner   = gamer     decomposes ask -> spec envelope
    Engineer  = diamond   claims spec, builds, posts artifact envelope
    Reviewer  = club      runs can-fail gate, posts verdict envelope
    Coordinator = nucleus recruits, routes, grants consent, calls done

THE constraint: Band is the transport, not a mirror. Loop agents consume
workflow state ONLY from Band rooms. The local bus gets a write-only
archival copy (band_archive.jsonl — deliberately NOT a role bus file, so
no inbox daemon can dispatch from it and the consume path stays Band-only).
Club's kill test makes this falsifiable: sever Band -> loop MUST stall.

SDK seam: every band-sdk touch lives in BandTransport. The SDK is not
installed until kickoff (Jun 12) — everything else here runs and tests
offline. When the real API lands, only BandTransport changes.

ADAPTER DECISION (spec rev 18:31, spade finding 1): the claude_sdk adapter
is @MENTION-TRIGGERED — an agent wakes only when mentioned. We ship path
(a): every handoff @mentions the next role (behaviors return explicit
to_role targets, so each reply IS a mention). Do NOT assume native push.
Path (b), the A2A Adapter, is fallback only if (a) drops mentions.

Offline selftest: py -3.12 apps/band/band_agent.py --selftest
Run live (post-kickoff): py -3.12 apps/band/band_agent.py --role diamond
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import consent    # noqa: E402
import envelopes  # noqa: E402


def _cell_root():
    """Cell mode iff the K-Cell layout exists (KCELL_ROOT overrides for
    tests — point it at an empty dir to force standalone mode)."""
    root = Path(os.environ.get("KCELL_ROOT", "C:/kit.triv"))
    return root if (root / "cell").exists() else None

_ROOT = _cell_root()
ARCHIVE = (_ROOT / "cell" / "bus" / "band_archive.jsonl") if _ROOT \
    else _HERE / "band_archive.jsonl"
USAGE_LOG = (_ROOT / "cell" / "usage_log.jsonl") if _ROOT \
    else _HERE / "usage_log.jsonl"

LOOP_ROLES = ("gamer", "diamond", "club", "nucleus")

# ------------------------------------------------------------------ config

def load_env(path=None):
    """Parse apps/band/.env -> dict (same pattern as fable_ping.py)."""
    env = {}
    p = Path(path) if path else _HERE / ".env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def load_agent_config(role, path=None):
    """agent_config.yaml -> {agent_id, api_key} for one role.
    Raises with a fix-it message if the role is missing or unfilled."""
    import yaml
    p = Path(path) if path else _HERE / "agent_config.yaml"
    if not p.exists():
        raise FileNotFoundError(
            "%s not found - cp agent_config.example.yaml agent_config.yaml "
            "and fill credentials from app.band.ai/dashboard" % p)
    config = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    entry = config.get(role)
    if not entry:
        raise KeyError("role '%s' not in agent_config.yaml (have: %s)"
                       % (role, ", ".join(sorted(config))))
    if "<" in str(entry.get("agent_id", "")) or "<" in str(entry.get("api_key", "")):
        raise ValueError(
            "role '%s' still has placeholder credentials - create the "
            "Remote Agent at app.band.ai/dashboard and paste UUID + key"
            % role)
    return entry


# --------------------------------------------------------- archival mirror

def mirror_to_archive(envelope, direction):
    """WRITE-ONLY telemetry copy of Band traffic to the local archive.

    Consume-path law: nothing in this module (or any loop agent) READS
    this file. It exists for Kit's telemetry and the submission transcript.
    Club's gate leg 3 inspects exactly this property.
    """
    try:
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "direction": direction,  # sent | received
            "envelope": envelope,
        }
        with open(ARCHIVE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        sys.stderr.write("archive mirror error (non-fatal): %s\n" % e)


def telemetry_snapshot(role):
    """Honest per-role telemetry from cell/usage_log.jsonl for envelope
    telemetry fields. Defensive parse; returns zeros if log absent."""
    cost, exchanges = 0.0, 0
    try:
        with open(USAGE_LOG, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("role") == role:
                    exchanges += 1
                    cost += float(rec.get("cost_usd", 0) or 0)
    except OSError:
        pass
    return {"cost_usd": round(cost, 4), "exchanges": exchanges}


# ------------------------------------------------------------- behaviors

class RoleBehavior:
    """Base: receives validated envelopes, returns reply envelopes.

    Handlers return a list of (to_role, envelope, prose) tuples; the
    transport posts them as @mentions. Pure functions of state -> fully
    offline-testable, which is how the doctrine rules below get gated
    before the SDK even exists locally.
    """

    def __init__(self, role):
        self.role = role

    def handle(self, env, sender):
        problems = envelopes.validate(env)
        if problems:
            return self.reject(env, problems)
        handler = getattr(self, "on_" + env.get("kind", ""), None)
        if handler is None:
            return []
        return handler(env, sender)

    def reject(self, env, problems):
        """REJECT path: a failing verdict with the validation errors as
        receipts. Evidence, not conclusions — the sender sees exactly
        which law their envelope broke."""
        verdict = envelopes.make_envelope(
            "verdict", env.get("task_id") or "unknown", self.role,
            env.get("from") or "unknown",
            verdict={"gate": "envelope-validation", "result": "FAIL",
                     "receipts": "validate() problems:\n- "
                                 + "\n- ".join(problems)
                                 + "\n\noffending envelope:\n"
                                 + json.dumps(env, indent=2)[:2000]})
        return [(env.get("from") or "room", verdict,
                 "Envelope REJECTED — fix and resend.")]


class PlannerBehavior(RoleBehavior):
    """Gamer: decompose the ask into a spec envelope. The decomposition
    itself is the agent's LLM turn; this class shapes the handoff."""

    def plan(self, task_id, ask, spec_body):
        env = envelopes.make_envelope(
            "spec", task_id, self.role, "diamond",
            telemetry=telemetry_snapshot(self.role))
        env["spec"] = {"ask": ask, "body": spec_body}
        return [("diamond", env, "Spec ready — @diamond it's yours.")]


class EngineerBehavior(RoleBehavior):
    """Diamond: claim spec, build, post artifact. Blocks on unsafe actions."""

    def __init__(self, role):
        super().__init__(role)
        self.blocked_on = None  # pending consent_request envelope

    def on_spec(self, env, sender):
        # The build itself is the agent's LLM turn (SDK adapter executes
        # tools). This handler acknowledges the claim; post_artifact()
        # ships the result when the build lands.
        return []

    def guard_action(self, task_id, action_kind, target, why=""):
        """Consent gate: returns ([], allowed=True) or the consent_request
        to post. Caller MUST NOT perform the action until granted."""
        if not consent.requires_consent(action_kind, target):
            return [], True
        if consent.check_grant(self.role, action_kind, target):
            return [], True
        req = consent.make_consent_request(task_id, self.role,
                                           action_kind, target, why)
        self.blocked_on = req
        return [("nucleus", req,
                 "BLOCKED on unsafe action — requesting consent.")], False

    def on_consent_grant(self, env, sender):
        consent.record_grant(env)
        self.blocked_on = None
        return []

    def post_artifact(self, task_id, repo, ref, path, note=""):
        env = envelopes.make_envelope(
            "artifact", task_id, self.role, "club",
            artifact={"repo": repo, "ref": ref, "path": path},
            telemetry=telemetry_snapshot(self.role))
        return [("club", env, note or "Built — @club gate it.")]


class ReviewerBehavior(RoleBehavior):
    """Club: pull artifact, run can-fail gate, post verdict. The validation
    REJECT in handle() already enforces 'no artifact without a ref'."""

    def on_artifact(self, env, sender):
        # The actual gate run is the agent's LLM/tool turn; post_verdict()
        # carries its RAW output. Receiving a valid artifact just queues it.
        return []

    def post_verdict(self, task_id, gate, result, raw_receipts):
        env = envelopes.make_envelope(
            "verdict", task_id, self.role, "nucleus",
            verdict={"gate": gate, "result": result,
                     "receipts": raw_receipts},
            telemetry=telemetry_snapshot(self.role))
        return [("nucleus", env, "Gate ran — verdict attached.")]


class CoordinatorBehavior(RoleBehavior):
    """Nucleus: recruit, route, grant/deny consent, call done — only on PASS."""

    def __init__(self, role):
        super().__init__(role)
        self.verdicts = {}  # task_id -> last verdict object

    def on_verdict(self, env, sender):
        self.verdicts[env["task_id"]] = env["verdict"]
        if env["verdict"]["result"] == "PASS":
            return self.emit_done(env["task_id"])
        return [("diamond", env,
                 "Gate FAILED — receipts attached, fix and resubmit.")]

    def on_consent_request(self, env, sender):
        # Policy turn: the coordinator (or Kit at a stop) decides. The
        # decision itself happens in the agent's LLM turn / human review;
        # grant() and deny() shape the reply.
        return []

    def grant(self, env, approved=True, ttl_minutes=30):
        reply = consent.make_consent_grant(env["task_id"], self.role, env,
                                           approved=approved,
                                           ttl_minutes=ttl_minutes)
        verb = "GRANTED" if approved else "DENIED"
        return [(env["from"], reply, "Consent %s." % verb)]

    def emit_done(self, task_id):
        """Refuses without a PASS verdict — the refusal is law, and the
        done envelope EMBEDS the verdict so any receiver can re-check."""
        verdict = self.verdicts.get(task_id)
        if not verdict or verdict.get("result") != "PASS":
            raise PermissionError(
                "refusing done for %s: no PASS verdict on record (have: %s)"
                % (task_id, verdict))
        env = envelopes.make_envelope(
            "done", task_id, self.role, "room", verdict=verdict,
            telemetry=telemetry_snapshot(self.role))
        return [("room", env, "Loop complete — verdict embedded.")]


BEHAVIORS = {
    "gamer": PlannerBehavior,
    "diamond": EngineerBehavior,
    "club": ReviewerBehavior,
    "nucleus": CoordinatorBehavior,
}


# ------------------------------------------------------------ SDK seam

class BandTransport:
    """EVERY band-sdk touch lives here. Until the SDK is installed and the
    kickoff docs confirm the exact API, this raises with instructions
    instead of pretending — BUILT, not yet VERIFIED-RUNNABLE."""

    def __init__(self, role, env=None, config=None):
        self.role = role
        self.env = env or load_env()
        self.config = config or load_agent_config(role)

    def connect(self):
        try:
            import band_sdk  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "band-sdk not installed. Run: "
                "py -3.12 -m pip install \"band-sdk[claude_sdk]\" "
                "(API access + docs land at the Jun 12 kickoff). "
                "Exact Agent.create() wiring is the ONLY code that "
                "changes — see BandTransport.")
        # KICKOFF-DAY SEAM — confirm against docs.band.ai SDK tutorial:
        #   from band_sdk import Agent
        #   self.agent = Agent.create(
        #       adapter="claude_sdk",
        #       agent_id=self.config["agent_id"],
        #       api_key=self.config["api_key"],
        #       ws_url=self.env["THENVOI_WS_URL"],
        #       rest_url=self.env["THENVOI_REST_URL"])
        raise NotImplementedError(
            "band-sdk installed but transport wiring awaits kickoff docs")

    def post(self, to_role, text):
        raise NotImplementedError("connect() first")


class BandCellAgent:
    """One cell role on Band: transport + behavior + the receive loop."""

    def __init__(self, role, transport=None):
        if role not in BEHAVIORS:
            raise ValueError("role must be one of %s" % (LOOP_ROLES,))
        self.role = role
        self.behavior = BEHAVIORS[role](role)
        self.transport = transport

    def receive(self, message_text, sender):
        """One inbound @mention -> zero or more outbound posts.
        This is the whole loop step, and it is SDK-free on purpose."""
        env, err = envelopes.extract(message_text)
        if env is None:
            # Plain prose (recruiting chatter etc.) — no envelope, no action.
            return []
        mirror_to_archive(env, "received")
        replies = self.behavior.handle(env, sender)
        for to_role, reply_env, prose in replies:
            mirror_to_archive(reply_env, "sent")
        return replies

    def run(self):
        """Live loop: connect and pump @mentions through receive()."""
        transport = self.transport or BandTransport(self.role)
        transport.connect()  # raises until kickoff wiring lands
        # KICKOFF-DAY SEAM: subscribe to mentions; for each message ->
        #   for to, env, prose in self.receive(msg.text, msg.sender):
        #       transport.post(to, envelopes.render(env, prose))


# ------------------------------------------------------------------ selftest

def _selftest():
    import tempfile

    # Redirect the archive: test envelopes must never contaminate the
    # honest-telemetry transcript the submission is built from.
    global ARCHIVE
    _tmp = tempfile.TemporaryDirectory()
    ARCHIVE = Path(_tmp.name) / "band_archive.jsonl"

    failures = []
    ran = []

    def check(name, cond):
        ran.append(name)
        print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
        if not cond:
            failures.append(name)

    print("band_agent.py offline selftest (no SDK, no network, temp archive)")

    club = BandCellAgent("club")
    nucleus = BandCellAgent("nucleus")
    diamond = BandCellAgent("diamond")

    # -- Reviewer REJECTS artifact missing ref (receiver-side law)
    bad = envelopes.render({"kind": "artifact", "task_id": "band-t1",
                            "from": "diamond", "to": "club",
                            "artifact": {"repo": "https://github.com/x/y"}})
    replies = club.receive(bad, "diamond")
    check("club REJECTS no-ref artifact with FAIL verdict",
          len(replies) == 1
          and replies[0][1]["kind"] == "verdict"
          and replies[0][1]["verdict"]["result"] == "FAIL"
          and "ref" in replies[0][1]["verdict"]["receipts"])

    # -- NEGATIVE CONTROL: well-formed artifact is NOT rejected
    good = envelopes.render(envelopes.make_envelope(
        "artifact", "band-t1", "diamond", "club",
        artifact={"repo": "https://github.com/x/y", "ref": "abc1234",
                  "path": "src/m.py"}))
    check("NEGCONTROL valid artifact passes (queued, no reject)",
          club.receive(good, "diamond") == [])

    # -- Coordinator refuses done without PASS
    refused = False
    try:
        nucleus.behavior.emit_done("band-t1")
    except PermissionError:
        refused = True
    check("nucleus REFUSES done with no verdict on record", refused)

    # -- FAIL verdict routes back to engineer, does NOT close
    fail_verdict = envelopes.render(envelopes.make_envelope(
        "verdict", "band-t1", "club", "nucleus",
        verdict={"gate": "kill-test", "result": "FAIL",
                 "receipts": "$ gate.py\n2/14 checks failed"}))
    replies = nucleus.receive(fail_verdict, "club")
    check("FAIL verdict bounces to diamond, no done emitted",
          len(replies) == 1 and replies[0][0] == "diamond")
    refused = False
    try:
        nucleus.behavior.emit_done("band-t1")
    except PermissionError:
        refused = True
    check("nucleus still refuses done after FAIL verdict", refused)

    # -- PASS verdict closes the loop with verdict embedded
    pass_verdict = envelopes.render(envelopes.make_envelope(
        "verdict", "band-t1", "club", "nucleus",
        verdict={"gate": "kill-test", "result": "PASS",
                 "receipts": "$ gate.py\n14/14 checks passed"}))
    replies = nucleus.receive(pass_verdict, "club")
    check("PASS verdict -> done emitted with verdict embedded",
          len(replies) == 1
          and replies[0][1]["kind"] == "done"
          and replies[0][1]["verdict"]["result"] == "PASS")

    # -- Engineer consent flow: unsafe action blocks, grant unblocks
    posts, allowed = diamond.behavior.guard_action(
        "band-t1", "net_push", "github.com/public-repo",
        why="submission push")
    check("diamond BLOCKS on net_push and posts consent_request",
          not allowed and len(posts) == 1
          and posts[0][1]["kind"] == "consent_request")

    # -- NEGATIVE CONTROL: safe action does not block
    posts, allowed = diamond.behavior.guard_action(
        "band-t1", "bash", "echo hello")
    check("NEGCONTROL safe bash is allowed without consent",
          allowed and posts == [])

    # -- prose without envelope is ignored, not crashed on
    check("plain prose (no envelope) yields no replies",
          club.receive("hi club, welcome to the room!", "nucleus") == [])

    # -- transport honestly refuses without SDK
    refused = False
    try:
        BandTransport.connect(
            type("T", (), {"role": "diamond", "env": {}, "config": {}})())
    except (RuntimeError, NotImplementedError):
        refused = True
    check("transport raises (not fakes) without band-sdk", refused)

    print("%d/%d checks passed" % (len(ran) - len(failures), len(ran)))
    if failures:
        print("FAILURES: %s" % ", ".join(failures))
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=LOOP_ROLES)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest or not args.role:
        _selftest()
    else:
        BandCellAgent(args.role).run()
