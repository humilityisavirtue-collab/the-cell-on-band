"""ChapterStage learning-loop envelope schema — parallel KIND-set to envelopes.py.

ChapterStage turns a book chapter into a VERIFIED interactive learning module via
a visible team of agents (deck: chapterstage_band_product_flow.pptx). It rides the
SAME Band transport and the SAME bus doctrine as the K-Cell 4-loop — so this module
REUSES envelopes.py's transport (render/extract) and verdict-check, and only adds
the learning KINDS. The 4-loop enum is NOT touched (spade boundary: add alongside).

Artifact chain (deck slide 7), each link a KIND here:
  knowledge_pack  structure  -> pedagogy/brainstorm  (chapter decomposed + cited)
  brainstorm_score brainstorm -> coordinator          (a scored variant from the loop)
  storyboard      visual     -> verifier              (interactive scene plan JSON)
  module          verifier   -> coordinator           (the VERIFIED terminal module)

REJECT rules carry the product thesis as mechanical law, not vibes:
  - knowledge_pack WITHOUT a source_ref is REJECTED. A pack with no source is a
    hallucination, not a decomposition — faithfulness starts at the root.
  - brainstorm_score WITHOUT its driving metric is REJECTED. A score without the
    metric that produced it is a vibe (attractor razor: the metric decides if a
    compression is meaning or junk).
  - module WITHOUT an embedded PASS verdict is REJECTED. "VERIFIED module" is the
    whole pitch; it is exactly the 4-loop's done-only-on-PASS gate, reused — a
    module is not done unless the verifier's faithfulness gate passed WITH receipts.

Pure stdlib. Selftest: py -3.12 apps/band/chapterstage_envelopes.py
(exits nonzero on any failure — a green that cannot be red is a report, not a gate.)
"""
from __future__ import annotations

import sys
from pathlib import Path

# envelopes.py lives beside this file; reuse its transport + verdict-check verbatim
sys.path.insert(0, str(Path(__file__).resolve().parent))
import envelopes  # noqa: E402  (render, extract, _check_verdict — transport-shared)

KINDS = frozenset({
    "knowledge_pack",   # structure -> pedagogy/brainstorm: chapter decomposed + cited
    "brainstorm_score", # brainstorm -> coordinator: one scored variant from the loop
    "storyboard",       # visual -> verifier: interactive scene plan (Storyboard JSON)
    "module",           # verifier -> coordinator: VERIFIED terminal module
})

ROLES = frozenset({
    "coordinator", "structure", "pedagogy", "brainstorm", "visual", "verifier",
})


# ---------------------------------------------------------------- construct

def make_envelope(kind, task_id, from_role, to_role, *, pack=None, score=None,
                  storyboard=None, verdict=None, telemetry=None):
    """Build a ChapterStage envelope. Raises ValueError on anything validate()
    would reject — fail at the source, not on the receiver's desk."""
    env = {"kind": kind, "task_id": task_id, "from": from_role, "to": to_role}
    if pack is not None:
        env["pack"] = pack
    if score is not None:
        env["score"] = score
    if storyboard is not None:
        env["storyboard"] = storyboard
    if verdict is not None:
        env["verdict"] = verdict
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

    Base field checks mirror envelopes.validate; learning kinds add their own
    receiver-side REJECT rules (see module docstring)."""
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

    if kind == "knowledge_pack":
        pack = env.get("pack")
        if not isinstance(pack, dict):
            problems.append("knowledge_pack has no pack object")
        else:
            src = pack.get("source_ref")
            if not isinstance(src, str) or not src.strip():
                problems.append("pack.source_ref missing or empty "
                                "(an uncited pack is a hallucination)")
            sections = pack.get("sections")
            if not isinstance(sections, list) or not sections:
                problems.append("pack.sections missing or empty "
                                "(nothing was decomposed)")

    if kind == "brainstorm_score":
        score = env.get("score")
        if not isinstance(score, dict):
            problems.append("brainstorm_score has no score object")
        else:
            metric = score.get("metric")
            if not isinstance(metric, str) or not metric.strip():
                problems.append("score.metric missing or empty "
                                "(a score without its metric is a vibe)")
            if not isinstance(score.get("value"), (int, float)) or \
                    isinstance(score.get("value"), bool):
                problems.append("score.value missing or not a number")
            vid = score.get("variant_id")
            if not isinstance(vid, str) or not vid.strip():
                problems.append("score.variant_id missing (which variant?)")

    if kind == "storyboard":
        sb = env.get("storyboard")
        if not isinstance(sb, dict):
            problems.append("storyboard has no storyboard object")
        else:
            scenes = sb.get("scenes")
            if not isinstance(scenes, list) or not scenes:
                problems.append("storyboard.scenes missing or empty "
                                "(no interactive plan to render)")

    if kind == "module":
        verdict_problems = envelopes._check_verdict(env.get("verdict"))
        if verdict_problems:
            problems.append("module must embed the faithfulness verdict it "
                            "relies on: " + "; ".join(verdict_problems))
        elif env["verdict"].get("result") != "PASS":
            problems.append("module with a non-PASS verdict — refuse to ship "
                            "(it is not a VERIFIED module)")

    return problems


# ------------------------------------------------------------ render/extract
# Transport is identical to the 4-loop — reuse verbatim so one bus carries both.
render = envelopes.render
extract = envelopes.extract


# ------------------------------------------------------------------ selftest

def _selftest():
    failures = []
    ran = []

    def check(name, cond):
        ran.append(name)
        print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
        if not cond:
            failures.append(name)

    print("chapterstage_envelopes.py selftest")

    # -- positive: well-formed knowledge_pack validates + round-trips
    pack = make_envelope(
        "knowledge_pack", "cs-001", "structure", "pedagogy",
        pack={"source_ref": "Young Wizards ch.3", "sections": ["intro", "Oath"],
              "ideas": ["wizardry as service"]})
    check("well-formed knowledge_pack validates clean", validate(pack) == [])
    msg = render(pack, prose="Chapter decomposed, over to you @pedagogy.")
    got, err = extract(msg)
    check("render->extract round-trip (shared transport)", got == pack and err == "")

    # -- NEGATIVE CONTROL: uncited pack MUST be rejected
    bad_pack = {"kind": "knowledge_pack", "task_id": "cs-001",
                "from": "structure", "to": "pedagogy",
                "pack": {"sections": ["intro"]}}
    check("NEGCONTROL uncited knowledge_pack is REJECTED",
          any("source_ref" in p for p in validate(bad_pack)))

    # -- NEGATIVE CONTROL: pack with no sections MUST be rejected
    empty_pack = {"kind": "knowledge_pack", "task_id": "cs-001",
                  "from": "structure", "to": "pedagogy",
                  "pack": {"source_ref": "ch.3", "sections": []}}
    check("NEGCONTROL knowledge_pack with empty sections is REJECTED",
          any("sections" in p for p in validate(empty_pack)))

    # -- positive: brainstorm_score with metric validates
    score = make_envelope(
        "brainstorm_score", "cs-001", "brainstorm", "coordinator",
        score={"variant_id": "v7", "metric": "source_faithfulness", "value": 0.82})
    check("well-formed brainstorm_score validates clean", validate(score) == [])

    # -- NEGATIVE CONTROL: score without its metric MUST be rejected
    bad_score = {"kind": "brainstorm_score", "task_id": "cs-001",
                 "from": "brainstorm", "to": "coordinator",
                 "score": {"variant_id": "v7", "value": 0.82}}
    check("NEGCONTROL brainstorm_score with no metric is REJECTED",
          any("metric" in p for p in validate(bad_score)))

    # -- NEGATIVE CONTROL: score value not a number MUST be rejected
    nan_score = {"kind": "brainstorm_score", "task_id": "cs-001",
                 "from": "brainstorm", "to": "coordinator",
                 "score": {"variant_id": "v7", "metric": "engagement",
                           "value": "high"}}
    check("NEGCONTROL brainstorm_score with non-numeric value is REJECTED",
          any("value" in p for p in validate(nan_score)))

    # -- positive: storyboard with scenes validates
    sb = make_envelope(
        "storyboard", "cs-001", "visual", "verifier",
        storyboard={"scenes": [{"id": 1, "kind": "interactive_oath"}]})
    check("well-formed storyboard validates clean", validate(sb) == [])

    # -- NEGATIVE CONTROL: storyboard with no scenes MUST be rejected
    empty_sb = {"kind": "storyboard", "task_id": "cs-001", "from": "visual",
                "to": "verifier", "storyboard": {"scenes": []}}
    check("NEGCONTROL storyboard with no scenes is REJECTED",
          any("scenes" in p for p in validate(empty_sb)))

    # -- positive: module embedding a PASS faithfulness verdict validates
    good_module = make_envelope(
        "module", "cs-001", "verifier", "coordinator",
        verdict={"gate": "source_faithfulness", "result": "PASS",
                 "receipts": "$ verify.py\n12/12 claims grounded in ch.3"})
    check("module embedding PASS verdict validates clean",
          validate(good_module) == [])

    # -- NEGATIVE CONTROL: module with FAIL verdict MUST be rejected
    fail_module = {"kind": "module", "task_id": "cs-001", "from": "verifier",
                   "to": "room",
                   "verdict": {"gate": "source_faithfulness", "result": "FAIL",
                               "receipts": "3 claims unsupported by source"}}
    check("NEGCONTROL module with FAIL verdict is REJECTED",
          any("non-PASS" in p for p in validate(fail_module)))

    # -- NEGATIVE CONTROL: module with NO verdict MUST be rejected
    no_v_module = {"kind": "module", "task_id": "cs-001", "from": "verifier",
                   "to": "room"}
    check("NEGCONTROL module with no verdict is REJECTED",
          any("embed the faithfulness verdict" in p for p in validate(no_v_module)))

    # -- make_envelope refuses to construct garbage
    refused = False
    try:
        make_envelope("knowledge_pack", "cs-002", "structure", "pedagogy",
                      pack={"sections": ["x"]})  # no source_ref
    except ValueError:
        refused = True
    check("make_envelope raises on invalid construction", refused)

    # -- NEGATIVE CONTROL: a 4-loop kind is NOT a ChapterStage kind
    foreign = {"kind": "spec", "task_id": "cs-001", "from": "gamer",
               "to": "diamond"}
    check("NEGCONTROL 4-loop 'spec' kind is REJECTED here",
          any("kind" in p for p in validate(foreign)))

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
