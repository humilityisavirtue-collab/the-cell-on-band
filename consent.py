"""Consent bridge: existing autonomy_gate -> Band consent envelopes.

Spec: cell/specs/BAND_OF_AGENTS_SPEC.md. Wheel-check: EXTENDS
satus/hooks/autonomy_gate.py — its destructive-pattern classifiers and its
consent_state.json grant ledger are reused, not re-derived. A grant given
in a Band room lands in the SAME ledger the PreToolUse hook reads, so the
two consent systems agree about what has been approved.

Loop law (demoed on camera): an agent classifies its own next action; if
unsafe it posts a consent_request @nucleus and BLOCKS until a consent_grant
envelope arrives. Diamond refusing to push without a grant is a demo
requirement, not a nice-to-have.

Selftest: py -3.12 apps/band/consent.py  (exits nonzero on failure; uses a
temp ledger — never touches the live consent_state.json.)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))                       # envelopes.py

# Cell mode: import the real organ from satus/hooks. Standalone (public
# repo): fall back to the _gate_fallback shim, which mirrors it. KCELL_ROOT
# overrides the root for tests — point it at an empty dir to force the
# fallback even on a machine that has the cell.
import os  # noqa: E402
_GATE_DIR = Path(os.environ.get("KCELL_ROOT", "C:/kit.triv")) / "satus" / "hooks"
if (_GATE_DIR / "autonomy_gate.py").exists():
    sys.path.insert(0, str(_GATE_DIR))
    import autonomy_gate as ag  # noqa: E402  (the existing organ, reused)
else:
    import _gate_fallback as ag  # noqa: E402  (public-repo shim, same organs)

import envelopes  # noqa: E402

# Action kinds the loop can classify. The spec's unsafe triad — file
# deletion, network push, spend — always needs consent; bash and file
# writes go through autonomy_gate's existing pattern classifiers.
ALWAYS_CONSENT = frozenset({"file_delete", "net_push", "spend"})


def requires_consent(action_kind, target):
    """True if this action must block on a consent_grant.

    action_kind: bash | file_write | file_delete | net_push | spend
    target: the command / path / amount being acted on
    """
    if action_kind in ALWAYS_CONSENT:
        return True
    if action_kind == "bash":
        return ag.is_destructive_command(target or "")
    if action_kind == "file_write":
        return ag.is_destructive_file(target or "")
    # Unknown action kinds fail CLOSED — a gate that defaults open is
    # decoration (gates-must-be-able-to-fail, source side).
    return True


# --------------------------------------------------------------- envelopes

def make_consent_request(task_id, from_role, action_kind, target,
                         why=""):
    """Build the consent_request envelope to post @nucleus."""
    action = "%s: %s" % (action_kind, target)
    if why:
        action += " — " + why
    return envelopes.make_envelope(
        "consent_request", task_id, from_role, "nucleus",
        consent={"required": True, "action": action, "granted_by": None,
                 "action_kind": action_kind, "target": target})


def make_consent_grant(task_id, granted_by, request_env,
                       approved=True, ttl_minutes=30):
    """Coordinator's reply. approved=False is an explicit denial —
    a refusal the requester can cite, not silence."""
    con = dict(request_env.get("consent") or {})
    con["granted_by"] = granted_by
    con["approved"] = bool(approved)
    con["ttl_minutes"] = ttl_minutes
    return envelopes.make_envelope(
        "consent_grant", task_id, granted_by, request_env.get("from", ""),
        consent=con)


# ------------------------------------------------------------------ ledger

def record_grant(grant_env, ledger_path=None):
    """Write a consent_grant into autonomy_gate's ledger format so
    check_grant() — and the live PreToolUse hook — both honor it."""
    import json
    path = Path(ledger_path) if ledger_path else ag.CONSENT_LOG
    con = grant_env.get("consent") or {}
    role = grant_env.get("to", "")
    key = "%s:%s:%s" % (role, con.get("action_kind", "band_action"),
                        str(con.get("target", ""))[:50])
    state = {}
    try:
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    state[key] = {
        "approved": bool(con.get("approved", False)),
        "approved_at": time.time(),
        "ttl_minutes": con.get("ttl_minutes", 30),
        "granted_by": con.get("granted_by", ""),
        "via": "band_room",
    }
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return key


def check_grant(role, action_kind, target, ledger_path=None):
    """True if a live (unexpired, approved) grant exists for this action."""
    if ledger_path:
        original = ag.CONSENT_LOG
        ag.CONSENT_LOG = Path(ledger_path)
        try:
            return ag.check_consent(role, action_kind, str(target)[:50])
        finally:
            ag.CONSENT_LOG = original
    return ag.check_consent(role, action_kind, str(target)[:50])


# ------------------------------------------------------------------ selftest

def _selftest():
    import json
    import tempfile

    failures = []
    ran = []

    def check(name, cond):
        ran.append(name)
        print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
        if not cond:
            failures.append(name)

    print("consent.py selftest (temp ledger, live state untouched)")

    # -- classification: spec triad always blocks
    check("file_delete requires consent", requires_consent("file_delete", "x"))
    check("net_push requires consent", requires_consent("net_push", "origin"))
    check("spend requires consent", requires_consent("spend", "$4.00"))

    # -- classification via autonomy_gate patterns
    check("rm -rf classified destructive",
          requires_consent("bash", "rm -rf build/"))
    check(".env write classified destructive",
          requires_consent("file_write", "apps/band/.env"))

    # -- NEGATIVE CONTROL: safe actions must NOT require consent
    check("NEGCONTROL plain echo does NOT require consent",
          not requires_consent("bash", "echo hello"))
    check("NEGCONTROL ordinary file write does NOT require consent",
          not requires_consent("file_write", "apps/band/notes.md"))

    # -- unknown kinds fail closed
    check("unknown action kind fails CLOSED",
          requires_consent("teleport", "anywhere"))

    # -- request -> grant -> ledger round-trip on a TEMP ledger
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "consent_state.json"
        req = make_consent_request("band-001", "diamond", "net_push",
                                   "public repo", why="submission push")
        check("consent_request envelope validates",
              envelopes.validate(req) == [])
        grant = make_consent_grant("band-001", "nucleus", req,
                                   approved=True, ttl_minutes=30)
        check("consent_grant envelope validates",
              envelopes.validate(grant) == [])
        record_grant(grant, ledger_path=ledger)
        check("granted action checks TRUE",
              check_grant("diamond", "net_push", "public repo",
                          ledger_path=ledger))

        # -- NEGATIVE CONTROL: ungranted action checks False
        check("NEGCONTROL ungranted action checks FALSE",
              not check_grant("diamond", "spend", "$999",
                              ledger_path=ledger))

        # -- NEGATIVE CONTROL: explicit denial checks False
        denial = make_consent_grant("band-001", "nucleus", req,
                                    approved=False)
        record_grant(denial, ledger_path=ledger)
        check("NEGCONTROL explicit denial checks FALSE",
              not check_grant("diamond", "net_push", "public repo",
                              ledger_path=ledger))

        # -- expiry honored (backdate past ttl)
        state = json.loads(ledger.read_text(encoding="utf-8"))
        for v in state.values():
            v["approved"] = True
            v["approved_at"] = time.time() - 3600
            v["ttl_minutes"] = 5
        ledger.write_text(json.dumps(state), encoding="utf-8")
        check("NEGCONTROL expired grant checks FALSE",
              not check_grant("diamond", "net_push", "public repo",
                              ledger_path=ledger))

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
    _selftest()
