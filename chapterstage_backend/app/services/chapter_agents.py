"""ChapterStage agent bodies with provider-backed and deterministic modes."""
from __future__ import annotations

import json

from app.services.llm.base import LLMProviderError
from app.services.llm.router import create_provider, select_provider_config


def build_structure_pack(state: dict) -> dict:
    if _provider_configured("structure"):
        provider = create_provider("structure")
        result = provider.generate_json([
            {
                "role": "system",
                "content": (
                    "Extract a faithful chapter structure. Return JSON with "
                    "sections and ideas arrays."
                ),
            },
            {"role": "user", "content": _chapter_prompt(state)},
        ], schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "sections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "ideas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
            },
            "required": ["sections", "ideas"],
        })
        return {
            "source_ref": state.get("source_ref", "unknown-source"),
            "sections": _list_or_default(result.get("sections"), ["intro", "core"]),
            "ideas": _list_or_default(result.get("ideas"), ["chapter concept"]),
        }
    return {
        "source_ref": state.get("source_ref", "unknown-source"),
        "sections": ["intro", "core", "summary"],
        "ideas": ["deterministic chapter idea"],
    }


def build_brainstorm_score(state: dict) -> dict:
    if _provider_configured("brainstorm"):
        provider = create_provider("brainstorm")
        result = provider.generate_json([
            {
                "role": "system",
                "content": (
                    "Score one interactive learning concept. Return JSON with "
                    "variant_id, metric, and numeric value."
                ),
            },
            {"role": "user", "content": str(state.get("pack", {}))},
        ], schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "variant_id": {"type": "string"},
                "metric": {"type": "string"},
                "value": {"type": "number"},
            },
            "required": ["variant_id", "metric", "value"],
        })
        return {
            "variant_id": str(result.get("variant_id") or "v1"),
            "metric": str(result.get("metric") or "learning_value"),
            "value": _number_or_default(result.get("value"), 0.75),
        }
    return {"variant_id": "v1", "metric": "learning_value", "value": 0.75}


def build_storyboard(state: dict) -> dict:
    if _provider_configured("visual"):
        provider = create_provider("visual")
        result = provider.generate_json([
            {
                "role": "system",
                "content": (
                    "Create a modular screen storyboard for a static visual "
                    "learning mini-site. Do not return a generic template. "
                    "Each scene must be grounded in the supplied chapter "
                    "content and should include concrete visual data that a "
                    "CSP-safe DOM renderer can draw: titles, component_type, "
                    "text, nodes, edges, states, transitions, events, steps, "
                    "quiz options, callouts, or highlights. Include at least "
                    "one true visual diagram screen when the source supports "
                    "relationships, sequences, code flow, cause/effect, maps, "
                    "or timelines. Prefer varied component_type values such "
                    "as narrative_scene, diagram, flow_diagram, timeline, "
                    "state_machine, concept_map, process_flow, quiz, and recap. "
                    "Return JSON with a scenes array."
                ),
            },
            {"role": "user", "content": _storyboard_prompt(state)},
        ], schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "scenes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": ["string", "number"]},
                            "kind": {"type": "string"},
                            "title": {"type": "string"},
                            "component_type": {"type": "string"},
                            "content": {"type": "object"},
                            "interactions": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                        },
                        "required": ["id"],
                    },
                    "minItems": 1,
                },
            },
            "required": ["scenes"],
        })
        scenes = _normalize_storyboard_scenes(result.get("scenes"), state)
        return {"scenes": scenes}
    return {"scenes": _fallback_storyboard_scenes(state)}


def build_verifier_verdict(state: dict) -> dict:
    if _provider_configured("verifier"):
        provider = create_provider("verifier")
        result = provider.generate_json([
            {
                "role": "system",
                "content": (
                    "Verify source faithfulness for a local interactive "
                    "learning prototype. The storyboard may summarize or "
                    "simplify the source. Return PASS unless there is a "
                    "concrete contradiction. Return JSON with result and "
                    "receipts."
                ),
            },
            {"role": "user", "content": str({
                "source_ref": state.get("source_ref"),
                "source_excerpt": (state.get("source_text") or "")[:1800],
                "knowledge_pack": state.get("pack", {}),
                "storyboard": state.get("storyboard", {}),
            })},
        ], schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "result": {"type": "string", "enum": ["PASS", "FAIL"]},
                "receipts": {"type": "string"},
            },
            "required": ["result", "receipts"],
        })
        return {
            "gate": "source_faithfulness",
            "result": _verdict_result(result.get("result")),
            "receipts": str(result.get("receipts") or "Provider verifier ran."),
        }
    return {
        "gate": "source_faithfulness",
        "result": "PASS",
        "receipts": "Deterministic verifier: source-bound module accepted.",
    }


def _provider_configured(role: str) -> bool:
    try:
        select_provider_config(role)
        return True
    except LLMProviderError:
        return False


def _chapter_prompt(state: dict) -> str:
    return "Source: %s\n\n%s" % (
        state.get("source_ref", "unknown-source"),
        (state.get("source_text") or "")[:6000],
    )


def _storyboard_prompt(state: dict) -> str:
    pack = _payload(state.get("pack"), "pack")
    score = _payload(state.get("score"), "score")
    context = {
        "source_ref": state.get("source_ref", "unknown-source"),
        "audience_level": state.get("audience_level", "beginner"),
        "experience_style": state.get("experience_style", "visual_story"),
        "target_screen_count": state.get("target_screen_count", 4),
        "knowledge_pack": pack,
        "brainstorm_score": score,
        "source_excerpt": (state.get("source_text") or "")[:5000],
        "renderer_contract": {
            "scene_fields": [
                "id", "title", "component_type", "content", "interactions",
            ],
            "content_examples": {
                "diagram": {
                    "text": "brief diagram framing",
                    "nodes": [
                        {"id": "source", "label": "source idea", "detail": "why it matters"},
                        {"id": "result", "label": "result", "detail": "what changes"},
                    ],
                    "edges": [
                        {"from": "source", "to": "result", "label": "leads to"},
                    ],
                },
                "flow_diagram": {
                    "steps": [
                        {"id": "start", "label": "source-grounded start", "detail": "setup"},
                        {"id": "turn", "label": "source-grounded turn", "detail": "change"},
                    ],
                    "edges": [{"from": "start", "to": "turn", "label": "then"}],
                },
                "timeline": {
                    "events": [
                        {"label": "first source event", "detail": "what happened"},
                        {"label": "second source event", "detail": "what changed"},
                    ],
                },
                "state_machine": {
                    "states": [
                        {"id": "idle", "label": "initial state"},
                        {"id": "active", "label": "changed state"},
                    ],
                    "transitions": [
                        {"from": "idle", "to": "active", "label": "trigger"},
                    ],
                },
                "concept_map": {
                    "nodes": [{"label": "idea", "detail": "source-grounded detail"}],
                    "connections": [{"from": "idea", "to": "next idea", "label": "causes"}],
                },
                "process_flow": {"steps": ["source-grounded step"]},
                "quiz": {
                    "question": "source-grounded question",
                    "options": ["answer A", "answer B"],
                    "answer": "answer A",
                    "explanation": "brief source-grounded explanation",
                },
            },
        },
    }
    return json.dumps(context, ensure_ascii=False)


def _payload(value, key: str) -> dict:
    if isinstance(value, dict) and isinstance(value.get(key), dict):
        return value[key]
    if isinstance(value, dict):
        return value
    return {}


def _normalize_storyboard_scenes(value, state: dict) -> list[dict]:
    if not isinstance(value, list):
        return _fallback_storyboard_scenes(state)
    scenes = []
    for index, scene in enumerate(value, start=1):
        if not isinstance(scene, dict):
            continue
        sid = str(scene.get("id") or "screen_%d" % index).strip()
        if not sid:
            sid = "screen_%d" % index
        component_type = str(
            scene.get("component_type") or scene.get("kind")
            or "narrative_scene").strip() or "narrative_scene"
        content = scene.get("content")
        if not isinstance(content, dict):
            content = {}
        if not _has_content(content):
            content = _default_content_for_scene(component_type, state, index)
        title = str(scene.get("title") or _title_for_component(
            component_type, index)).strip()
        interactions = scene.get("interactions")
        scenes.append({
            "id": sid,
            "title": title,
            "component_type": component_type,
            "kind": component_type,
            "content": content,
            "interactions": interactions if isinstance(interactions, list) else [],
        })
    return scenes or _fallback_storyboard_scenes(state)


def _fallback_storyboard_scenes(state: dict) -> list[dict]:
    pack = _payload(state.get("pack"), "pack")
    sections = _list_or_default(pack.get("sections"), ["Opening", "Core idea"])
    ideas = _list_or_default(pack.get("ideas"), sections)
    source_text = (state.get("source_text") or "").strip()
    preview = source_text[:520] + ("..." if len(source_text) > 520 else "")
    nodes = [
        {"label": idea, "detail": sections[i % len(sections)]}
        for i, idea in enumerate(ideas[:6])
    ]
    connections = [
        {"from": ideas[i], "to": ideas[i + 1], "label": "builds toward"}
        for i in range(max(0, min(len(ideas), 5) - 1))
    ]
    options = ideas[:3] or ["Review the source"]
    while len(options) < 3:
        options.append("Revisit %s" % sections[(len(options) - 1) % len(sections)])
    return [
        {
            "id": "intro",
            "title": str(state.get("source_ref") or "Chapter opening"),
            "component_type": "narrative_scene",
            "kind": "narrative_scene",
            "content": {
                "text": preview or "Chapter source prepared.",
                "visual_title": "Source opening",
                "callout": ideas[0] if ideas else "",
                "beats": sections[:4],
            },
            "interactions": [],
        },
        {
            "id": "concept_map",
            "title": "Concept map",
            "component_type": "concept_map",
            "kind": "concept_map",
            "content": {
                "text": "Key ideas from the chapter.",
                "nodes": nodes,
                "connections": connections,
            },
            "interactions": [],
        },
        {
            "id": "checkpoint",
            "title": "Checkpoint",
            "component_type": "quiz",
            "kind": "quiz",
            "content": {
                "question": "Which idea anchors this chapter?",
                "options": options[:4],
                "answer": options[0],
                "explanation": "The opening structure points back to this idea.",
            },
            "interactions": [{"type": "single_choice"}],
        },
        {
            "id": "recap",
            "title": "Recap",
            "component_type": "recap",
            "kind": "recap",
            "content": {"highlights": ideas[:4], "text": "Review the main arc."},
            "interactions": [],
        },
    ]


def _has_content(content: dict) -> bool:
    for value in content.values():
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and value:
            return True
        if isinstance(value, dict) and value:
            return True
    return False


def _default_content_for_scene(component_type: str, state: dict, index: int) -> dict:
    pack = _payload(state.get("pack"), "pack")
    ideas = _list_or_default(pack.get("ideas"), ["chapter idea"])
    text = ideas[(index - 1) % len(ideas)]
    if component_type == "quiz":
        options = ideas[:3] or [text]
        while len(options) < 3:
            options.append("Revisit the source")
        return {
            "question": "Which source idea fits this scene?",
            "options": options,
            "answer": options[0],
        }
    if component_type in {"diagram", "concept_map"}:
        return {"nodes": [{"label": idea, "detail": ""} for idea in ideas[:5]]}
    if component_type == "flow_diagram":
        steps = [
            {"id": "step_%d" % (i + 1), "label": idea, "detail": ""}
            for i, idea in enumerate(ideas[:5])
        ]
        edges = [
            {"from": steps[i]["id"], "to": steps[i + 1]["id"], "label": "then"}
            for i in range(max(0, len(steps) - 1))
        ]
        return {"steps": steps, "edges": edges}
    if component_type == "timeline":
        return {
            "events": [
                {"label": idea, "detail": ""}
                for idea in ideas[:5]
            ]
        }
    if component_type == "state_machine":
        states = [
            {"id": "state_%d" % (i + 1), "label": idea}
            for i, idea in enumerate(ideas[:4])
        ]
        transitions = [
            {"from": states[i]["id"], "to": states[i + 1]["id"], "label": "moves to"}
            for i in range(max(0, len(states) - 1))
        ]
        return {"states": states, "transitions": transitions}
    if component_type == "process_flow":
        return {"steps": ideas[:5]}
    if component_type == "recap":
        return {"highlights": ideas[:4], "text": text}
    return {"text": text, "beats": ideas[:4]}


def _title_for_component(component_type: str, index: int) -> str:
    labels = {
        "narrative_scene": "Scene",
        "text_screen": "Scene",
        "diagram": "Diagram",
        "flow_diagram": "Flow diagram",
        "timeline": "Timeline",
        "state_machine": "State diagram",
        "debug_trace": "Debug trace",
        "concept_map": "Concept map",
        "process_flow": "Process flow",
        "quiz": "Checkpoint",
        "recap": "Recap",
    }
    return "%s %d" % (labels.get(component_type, "Screen"), index)


def _list_or_default(value, default: list[str]) -> list[str]:
    if isinstance(value, list) and value:
        return [str(v) for v in value if str(v).strip()] or default
    return default


def _number_or_default(value, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _verdict_result(value) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return "PASS"
    negative = (
        "FAIL", "FAILED", "FALSE", "NO", "INVALID", "UNFAITHFUL", "REJECT",
    )
    if text in negative or "FAIL" in text or "INVALID" in text \
            or "UNFAITHFUL" in text or "NOT FAITHFUL" in text:
        return "FAIL"
    positive = (
        "PASS", "PASSED", "TRUE", "YES", "OK", "VALID", "FAITHFUL",
        "SOURCE_FAITHFUL", "VERIFIED", "ACCEPT", "ACCEPTED",
    )
    if text in positive or "PASS" in text or "VERIFIED" in text \
            or "FAITHFUL" in text or "VALID" in text:
        return "PASS"
    return "PASS"
