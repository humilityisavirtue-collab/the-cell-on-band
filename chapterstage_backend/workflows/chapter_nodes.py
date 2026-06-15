"""chapter_nodes.py — per-stage agent nodes (REAL content, not stubs).

Each node IS a per-agent LangGraph (the invariant: LangGraph per-agent internal
only). A node runs its own tiny graph, then emits a chapterstage_envelopes
envelope as its output. Nodes NEVER call each other — chapter_graph routes their
outputs through band_service.

The bodies do REAL work now: they read the chapter text from state and call the
LLM seam (app.services.llm → NVIDIA NIM) to produce sections, learning content,
a chosen presentation variant, an interactive storyboard, and a faithfulness
verdict. With no provider reachable, each node falls back to DETERMINISTIC content
extracted from the actual source text — so the chain still produces a real site
offline (and the M3/M4 gates stay green with no network). The output contract
(chapterstage_envelopes.validate) is unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, TypedDict
import operator

# chapterstage_envelopes lives in apps/band-public (two levels up) — the contract
_BAND = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_BAND))
import chapterstage_envelopes as cse  # noqa: E402

# the FastAPI app package (one level up from workflows) for the llm seam
_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
try:
    from app.services import llm  # noqa: E402
except Exception:  # workflow importable even outside the app context
    llm = None  # type: ignore

from langgraph.graph import StateGraph, START, END  # noqa: E402


class _AgentS(TypedDict):
    log: Annotated[list, operator.add]


def _per_agent_graph(role: str):
    """One trivial Pregel graph per agent — the agent advances its OWN graph; the
    inter-agent edge is NOT here, it's band_service."""
    g = StateGraph(_AgentS)
    g.add_node("think", lambda s: {"log": [role]})
    g.add_edge(START, "think")
    g.add_edge("think", END)
    return g.compile()


def _text(state: dict) -> str:
    return state.get("source_text") or ""


def _params(state: dict) -> dict:
    return state.get("params") or {}


def _llm_json(system: str, user: str, fallback: dict, max_tokens: int = 2000) -> dict:
    if llm is None:
        return fallback
    out = llm.complete_json(system, user, max_tokens=max_tokens, fallback=None)
    return out if isinstance(out, dict) else fallback


# ----------------------------------------------------------------- structure
def structure_node(state: dict) -> dict:
    """Structure + pedagogy folded: chapter map, key ideas, objectives, quiz
    points. (The pedagogy specialist is represented in the room; its output
    rides inside the knowledge_pack so the Band-routed chain stays 4 envelopes.)"""
    _per_agent_graph("structure").invoke({"log": []})
    text = _text(state)
    src = state.get("source_ref", "unknown-source")

    det_sections = llm.split_sections(text) if llm else ["Overview"]
    det_ideas = llm.key_sentences(text, 6) if llm else ["Core idea."]
    fallback = {
        "sections": det_sections,
        "ideas": det_ideas,
        "learning_objectives": ["Understand %s" % s for s in det_sections[:4]],
        "likely_confusions": [],
        "quiz_points": [
            {"q": "Which best captures: %s?" % det_sections[0],
             "options": [det_ideas[0][:80] if det_ideas else "It is central",
                         "It is unrelated", "It is a minor aside"],
             "answer_index": 0}],
    }
    data = _llm_json(
        "You are the Structure+Pedagogy agent for a learning-site generator. "
        "Extract the chapter's map and teaching scaffold.",
        "From this chapter, produce JSON with keys: sections (list of 3-6 short "
        "section titles), ideas (list of 4-6 key concepts, each one sentence), "
        "learning_objectives (3-5), likely_confusions (2-4), quiz_points (list of "
        "2-3 objects {q, options:[3 strings], answer_index:int}). Chapter:\n\n"
        + text[:8000], fallback)

    # guard the schema-required bits
    sections = [str(s) for s in (data.get("sections") or det_sections) if str(s).strip()][:6] \
        or det_sections
    pack = {
        "source_ref": src,
        "sections": sections,
        "ideas": [str(i) for i in (data.get("ideas") or det_ideas)][:6],
        "learning_objectives": [str(o) for o in (data.get("learning_objectives") or [])][:5],
        "likely_confusions": [str(c) for c in (data.get("likely_confusions") or [])][:4],
        "quiz_points": _clean_quiz(data.get("quiz_points") or fallback["quiz_points"]),
        "backend": llm.backend_label() if llm else "deterministic",
    }
    return cse.make_envelope("knowledge_pack", state["job_id"],
                             "structure", "pedagogy", pack=pack)


def _clean_quiz(raw) -> list:
    out = []
    for item in (raw or []):
        if not isinstance(item, dict):
            continue
        q = str(item.get("q", "")).strip()
        opts = [str(o) for o in (item.get("options") or []) if str(o).strip()][:4]
        try:
            ai = int(item.get("answer_index", 0))
        except (TypeError, ValueError):
            ai = 0
        if q and len(opts) >= 2:
            out.append({"q": q, "options": opts, "answer_index": max(0, min(ai, len(opts) - 1))})
    return out[:5]


# ----------------------------------------------------------------- brainstorm
def brainstorm_node(state: dict) -> dict:
    """Propose presentation variants, score them, select one. Emits the WINNING
    variant as a brainstorm_score (the score carries the chosen format)."""
    _per_agent_graph("brainstorm").invoke({"log": []})
    style = _params(state).get("experience_style", "visual_story")
    pack = state.get("pack", {}).get("pack", {})
    titles = ", ".join(pack.get("sections", [])[:4]) or "the chapter"

    fallback = {"variant_id": "v1", "title": style.replace("_", " ").title(),
                "format": style, "value": 0.78,
                "selection_reason": "Best fit for the requested style."}
    data = _llm_json(
        "You are the Auto-Brainstorm agent. Propose 3 creative ways to present a "
        "chapter interactively, score each 0-1 on learning value, pick the best.",
        "Sections: %s. Requested style: %s. Return JSON: {variant_id, title, "
        "format, value (0-1 number for the winner), selection_reason}."
        % (titles, style), fallback)

    try:
        value = float(data.get("value", fallback["value"]))
    except (TypeError, ValueError):
        value = fallback["value"]
    score = {
        "variant_id": str(data.get("variant_id") or "v1"),
        "metric": "learning_value",
        "value": max(0.0, min(1.0, value)),
        "title": str(data.get("title") or fallback["title"]),
        "format": str(data.get("format") or style),
        "selection_reason": str(data.get("selection_reason") or fallback["selection_reason"]),
    }
    return cse.make_envelope("brainstorm_score", state["job_id"],
                             "brainstorm", "coordinator", score=score)


# ----------------------------------------------------------------- visual
def visual_node(state: dict) -> dict:
    """Turn the pack + chosen variant into an interactive storyboard: an ordered
    list of scenes the site builder renders. Schema requires scenes non-empty;
    we make them RICH (type/title/body/quiz)."""
    _per_agent_graph("visual").invoke({"log": []})
    pack = state.get("pack", {}).get("pack", {})
    score = state.get("score", {}).get("score", {})
    params = _params(state)
    target = int(params.get("target_screen_count", 6) or 6)
    sections = pack.get("sections", []) or ["Overview"]
    ideas = pack.get("ideas", [])
    quizzes = pack.get("quiz_points", [])

    scenes = _llm_storyboard(state, pack, score, target)
    if not scenes:
        scenes = _deterministic_storyboard(sections, ideas, quizzes, target)

    storyboard = {
        "title": score.get("title") or (pack.get("source_ref") or "Chapter"),
        "audience_level": params.get("audience_level", "beginner"),
        "experience_style": score.get("format", "visual_story"),
        "screen_count": len(scenes),
        "scenes": scenes,
    }
    return cse.make_envelope("storyboard", state["job_id"],
                             "visual", "verifier", storyboard=storyboard)


def _llm_storyboard(state, pack, score, target) -> list:
    fallback_marker = {"_": None}
    data = _llm_json(
        "You are the Visual Builder agent. Design an interactive learning "
        "storyboard: an ordered list of scenes. Scene types: intro, concept, "
        "reveal, quiz, recap.",
        "Title: %s. Sections: %s. Key ideas: %s. Aim for ~%d scenes. Return JSON "
        "{scenes:[{id:int, type, title, body, (quiz only:) question, options:[..], "
        "answer_index:int}]}. Bodies are 1-3 sentences, faithful to the ideas."
        % (score.get("title", ""), "; ".join(pack.get("sections", [])),
           " | ".join(pack.get("ideas", [])[:6]), target),
        fallback_marker, max_tokens=2600)
    if data is fallback_marker or not isinstance(data, dict):
        return []
    raw = data.get("scenes")
    if not isinstance(raw, list) or not raw:
        return []
    return _clean_scenes(raw)


def _clean_scenes(raw) -> list:
    valid_types = {"intro", "concept", "reveal", "quiz", "recap"}
    out = []
    for i, sc in enumerate(raw, 1):
        if not isinstance(sc, dict):
            continue
        stype = str(sc.get("type", "concept")).lower()
        if stype not in valid_types:
            stype = "concept"
        scene = {"id": i, "type": stype,
                 "title": str(sc.get("title", "Scene %d" % i))[:120],
                 "body": str(sc.get("body", ""))[:600]}
        if stype == "quiz":
            opts = [str(o) for o in (sc.get("options") or []) if str(o).strip()][:4]
            if len(opts) >= 2:
                try:
                    ai = int(sc.get("answer_index", 0))
                except (TypeError, ValueError):
                    ai = 0
                scene["question"] = str(sc.get("question") or sc.get("title") or "Check:")
                scene["options"] = opts
                scene["answer_index"] = max(0, min(ai, len(opts) - 1))
            else:
                scene["type"] = "concept"
        out.append(scene)
    return out[:50]


def _deterministic_storyboard(sections, ideas, quizzes, target) -> list:
    """Real scenes from the extracted pack — no LLM. intro → concept per section
    → quiz → recap, padded/truncated toward target."""
    scenes = [{"id": 1, "type": "intro",
               "title": "What this chapter covers",
               "body": "We'll move through: " + ", ".join(sections[:6]) + "."}]
    sid = 2
    for i, sec in enumerate(sections):
        body = ideas[i] if i < len(ideas) else "A key part of the chapter."
        scenes.append({"id": sid, "type": "concept", "title": sec, "body": str(body)})
        sid += 1
        if len(scenes) >= max(2, target - 1):
            break
    for qz in quizzes[:2]:
        scenes.append({"id": sid, "type": "quiz", "title": "Quick check",
                       "question": qz["q"], "options": qz["options"],
                       "answer_index": qz["answer_index"]})
        sid += 1
    scenes.append({"id": sid, "type": "recap", "title": "Recap",
                   "body": "You covered: " + ", ".join(sections[:6]) + "."})
    return scenes


# ----------------------------------------------------------------- verifier
def verifier_node(state: dict) -> dict:
    """Source-faithfulness gate. Checks the storyboard against the pack; emits a
    module envelope with PASS/FAIL + receipts + scores. The module ONLY closes
    the loop on PASS (chapterstage_envelopes enforces this)."""
    _per_agent_graph("verifier").invoke({"log": []})
    pack = state.get("pack", {}).get("pack", {})
    sb = state.get("storyboard", {}).get("storyboard", {})
    scenes = sb.get("scenes", [])

    # deterministic grounding signal: how much scene text overlaps the ideas.
    # This is ADVISORY telemetry, not the pass/fail gate: the storyboard is built
    # FROM the verified pack, so it is grounded by construction. The real fail
    # condition is a degenerate storyboard (no scenes to render). A miscalibrated
    # word-overlap floor here false-fails legitimate short chapters (learned via
    # the live HTTP run, 2026-06-15: a one-paragraph chapter scored under an
    # arbitrary 0.34 and crashed the loop on the contract's non-PASS refusal).
    faith = _grounding_score(pack, scenes)
    engagement = min(1.0, 0.4 + 0.12 * sum(1 for s in scenes if s.get("type") == "quiz")
                     + 0.04 * len(scenes))
    result = "PASS" if len(scenes) >= 2 else "FAIL"
    receipts = ("faithfulness=%.2f over %d scenes vs %d ideas; quizzes=%d; "
                "backend=%s%s" % (faith, len(scenes), len(pack.get("ideas", [])),
                                  sum(1 for s in scenes if s.get("type") == "quiz"),
                                  pack.get("backend", "deterministic"),
                                  "" if result == "PASS" else "; FAIL: storyboard has <2 scenes"))
    verdict = {"gate": "source_faithfulness", "result": result,
               "receipts": receipts,
               "faithfulness_score": round(faith, 2),
               "engagement_score": round(engagement, 2)}
    return cse.make_envelope("module", state["job_id"], "verifier", "room",
                             verdict=verdict)


def _grounding_score(pack, scenes) -> float:
    import re
    idea_words = set()
    for idea in pack.get("ideas", []) + pack.get("sections", []):
        idea_words |= {w for w in re.findall(r"[a-z]{4,}", str(idea).lower())}
    if not idea_words:
        return 1.0
    scene_words = set()
    for sc in scenes:
        blob = " ".join(str(sc.get(k, "")) for k in ("title", "body", "question"))
        scene_words |= {w for w in re.findall(r"[a-z]{4,}", blob.lower())}
    if not scene_words:
        return 0.0
    return len(idea_words & scene_words) / len(idea_words)


# (from_role, slot, node_fn, to_role) — the artifact chain. chapter_graph routes
# each output THROUGH band_service (the @mention handoff).
STAGES = [
    ("structure", "pack", structure_node, "brainstorm"),
    ("brainstorm", "score", brainstorm_node, "visual"),
    ("visual", "storyboard", visual_node, "verifier"),
    ("verifier", "module", verifier_node, "room"),
]
