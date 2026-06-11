"""Handoff envelope schema + validation + REJECT logic for the Band 4-agent loop.

Spec: cell/specs/BAND_OF_AGENTS_SPEC.md. Shared by all four loop agents.
Every Band handoff message is prose + ONE fenced JSON envelope. Bus doctrine
rides the transport: evidence, not conclusions — so validation here is the
mechanical half of that law. An envelope that fails validation is REJECTED
by the receiver (Club doctrine, enforced in code).

Pure stdlib. No band-sdk dependency — this module must work offline so the
schema is testable before kickoff and inside Club's gate harness.

Selftest: py -3.12 apps/band/envelopes.py  (exits nonzero on any failure —
a green that cannot be red is a report, not a gate.)
"""
from __future__ import annotations

import json
import re
import sys

KINDS = frozenset({
    "spec",             # planner -> engineer: decomposed ask
    "artifact",         # engineer -> reviewer: built thing (repo+ref+path)
    "verdict",          # reviewer -> coordinator: can-fail gate result
    "consent_request",  # any -> coordinator: unsafe action, blocked, asking
    "consent_grant",    # coordinator -> requester: approved (or not)
    "done",             # coordinator -> room: loop complete (carries PASS verdict)
})

ROLES = frozenset({"gamer", "diamond", "club", "nucleus"})

VERDICT_RESULTS = frozenset({"PASS", "FAIL"})

_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


# ---------------------------------------------------------------- construct

def make_envelope(kind, task_id, from_role, to_role, *, artifact=None,
                  verdict=None, consent=None, telemetry=None):
    """Build an envelope dict. Raises ValueError on anything validate()
    would reject — fail at the source, not on the receiver's desk."""
    env = {
        "kind": kind,
        "task_id": task_id,
        "from": from_role,
        "to": to_role,
    }
    if artifact is not None:
        env["artifact"] = artifact
    if verdict is not None:
        env["verdict"] = verdict
    if consent is not None:
        env["consent"] = consent
    if telemetry is not None:
        env["telemetry"] = telemetry
    problems = validate(env)
    if problems:
        raise ValueError("refusing to construct invalid envelope: "
                         + "; ".join(problems))
    return env


# ----------------------------------------------------------------- validate

def validate(env):
    """Return a list of problems. Empty list = acceptable.

    REJECT rules (from the spec, receiver-side law):
      - artifact without a checkout-able ref -> reject
      - verdict without raw receipts -> reject (a verdict is its evidence)
      - done without an embedded PASS verdict -> reject (nucleus must not
        emit done on belief; embedding the verdict makes the rule checkable
        by ANY receiver, not just nucleus)
    """
    problems = []
    if not isinstance(env, dict):
        return ["envelope is not a JSON object"]

    kind = env.get("kind")
    if kind not in KINDS:
        problems.append("kind missing or not one of %s" % sorted(KINDS))

    for field in ("task_id", "from", "to"):
        v = env.get(field)
        if not isinstance(v, str) or not v.strip():
            problems.append("%s missing or empty" % field)

    if kind == "artifact":
        art = env.get("artifact")
        if not isinstance(art, dict):
            problems.append("artifact envelope has no artifact object")
        else:
            for field in ("repo", "ref"):
                v = art.get(field)
                if not isinstance(v, str) or not v.strip():
                    problems.append("artifact.%s missing or empty "
                                    "(receiver cannot check it out)" % field)

    if kind == "verdict":
        problems.extend(_check_verdict(env.get("verdict")))

    if kind == "consent_request":
        con = env.get("consent")
        if not isinstance(con, dict):
            problems.append("consent_request has no consent object")
        else:
            if con.get("required") is not True:
                problems.append("consent.required must be true")
            action = con.get("action")
            if not isinstance(action, str) or not action.strip():
                problems.append("consent.action missing or empty "
                                "(what is being asked?)")

    if kind == "consent_grant":
        con = env.get("consent")
        if not isinstance(con, dict):
            problems.append("consent_grant has no consent object")
        else:
            for field in ("action", "granted_by"):
                v = con.get(field)
                if not isinstance(v, str) or not v.strip():
                    problems.append("consent.%s missing or empty" % field)

    if kind == "done":
        verdict_problems = _check_verdict(env.get("verdict"))
        if verdict_problems:
            problems.append("done must embed the verdict it relies on: "
                            + "; ".join(verdict_problems))
        elif env["verdict"].get("result") != "PASS":
            problems.append("done with a non-PASS verdict — refuse to close")

    return problems


def _check_verdict(verdict):
    problems = []
    if not isinstance(verdict, dict):
        return ["no verdict object"]
    gate = verdict.get("gate")
    if not isinstance(gate, str) or not gate.strip():
        problems.append("verdict.gate missing (which gate ran?)")
    result = verdict.get("result")
    if result not in VERDICT_RESULTS:
        problems.append("verdict.result must be PASS or FAIL")
    receipts = verdict.get("receipts")
    if not isinstance(receipts, str) or not receipts.strip():
        problems.append("verdict.receipts missing or empty "
                        "(raw command output, not a summary)")
    return problems


# ------------------------------------------------------------ render/extract

def render(env, prose=""):
    """Envelope -> Band message text: prose + one fenced JSON block."""
    block = "```json\n" + json.dumps(env, indent=2) + "\n```"
    return (prose.rstrip() + "\n\n" + block) if prose.strip() else block


def extract(text):
    """Message text -> (envelope dict | None, error string).

    Tries fenced ```json blocks first. Falls back to scanning for a bare
    JSON object carrying a "kind" key — the spec's fallback for transports
    that mangle fences. Returns the FIRST envelope found.
    """
    if not isinstance(text, str) or not text.strip():
        return None, "empty message"

    for match in _FENCE_RE.finditer(text):
        candidate = match.group(1).strip()
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "kind" in obj:
            return obj, ""

    # Fence-mangled fallback: raw_decode at each '{'
    decoder = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = decoder.raw_decode(text[idx:])
            if isinstance(obj, dict) and "kind" in obj:
                return obj, ""
        except json.JSONDecodeError:
            pass
        idx = text.find("{", idx + 1)

    return None, "no JSON envelope found in message"


# ------------------------------------------------------------------ selftest

def _selftest():
    failures = []
    ran = []

    def check(name, cond):
        ran.append(name)
        status = "PASS" if cond else "FAIL"
        print("  [%s] %s" % (status, name))
        if not cond:
            failures.append(name)

    print("envelopes.py selftest")

    # -- positive: a well-formed artifact envelope round-trips
    art = make_envelope("artifact", "band-001", "diamond", "club",
                        artifact={"repo": "https://github.com/x/y",
                                  "ref": "abc1234", "path": "src/m.py"})
    check("well-formed artifact validates clean", validate(art) == [])
    msg = render(art, prose="Build done, over to you @club.")
    got, err = extract(msg)
    check("render->extract round-trip", got == art and err == "")

    # -- NEGATIVE CONTROL: artifact with no ref MUST be rejected
    bad_art = dict(art, artifact={"repo": "https://github.com/x/y"})
    check("NEGCONTROL artifact missing ref is REJECTED",
          any("ref" in p for p in validate(bad_art)))

    # -- NEGATIVE CONTROL: verdict with no receipts MUST be rejected
    bad_verdict = {"kind": "verdict", "task_id": "band-001",
                   "from": "club", "to": "nucleus",
                   "verdict": {"gate": "kill-test", "result": "PASS",
                               "receipts": ""}}
    check("NEGCONTROL verdict with empty receipts is REJECTED",
          any("receipts" in p for p in validate(bad_verdict)))

    # -- NEGATIVE CONTROL: done without PASS verdict MUST be rejected
    bad_done = {"kind": "done", "task_id": "band-001",
                "from": "nucleus", "to": "room",
                "verdict": {"gate": "kill-test", "result": "FAIL",
                            "receipts": "loop stalled at 60s as required"}}
    check("NEGCONTROL done with FAIL verdict is REJECTED",
          any("non-PASS" in p for p in validate(bad_done)))
    no_verdict_done = {"kind": "done", "task_id": "band-001",
                       "from": "nucleus", "to": "room"}
    check("NEGCONTROL done with NO verdict is REJECTED",
          any("embed the verdict" in p for p in validate(no_verdict_done)))

    # -- positive: done carrying a PASS verdict is accepted
    good_done = make_envelope(
        "done", "band-001", "nucleus", "room",
        verdict={"gate": "kill-test", "result": "PASS",
                 "receipts": "$ python gate.py\n14/14 checks passed"})
    check("done embedding PASS verdict validates clean",
          validate(good_done) == [])

    # -- make_envelope refuses to construct garbage
    refused = False
    try:
        make_envelope("artifact", "band-002", "diamond", "club",
                      artifact={"repo": "r"})  # no ref
    except ValueError:
        refused = True
    check("make_envelope raises on invalid construction", refused)

    # -- mangled fence still extracts (spec falsifier fallback)
    mangled = ('Sure! Here is the result `json {"kind": "spec", '
               '"task_id": "band-003", "from": "gamer", "to": "diamond"} '
               "hope that helps")
    got, err = extract(mangled)
    check("mangled fence falls back to raw-decode extraction",
          got is not None and got.get("kind") == "spec")

    # -- NEGATIVE CONTROL: prose with no envelope returns None + error
    got, err = extract("just chatting, no envelope here {not json}")
    check("NEGCONTROL envelope-free prose extracts to None", got is None and err != "")

    # -- consent kinds
    req = make_envelope("consent_request", "band-001", "diamond", "nucleus",
                        consent={"required": True,
                                 "action": "git push to public repo",
                                 "granted_by": None})
    check("consent_request validates clean", validate(req) == [])
    bad_req = {"kind": "consent_request", "task_id": "t", "from": "d",
               "to": "n", "consent": {"required": True, "action": ""}}
    check("NEGCONTROL consent_request with empty action is REJECTED",
          any("action" in p for p in validate(bad_req)))

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
