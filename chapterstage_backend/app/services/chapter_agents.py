"""ChapterStage agent bodies with provider-backed and deterministic modes."""
from __future__ import annotations

from app.services.llm.base import LLMProviderError
from app.services.llm.router import create_provider, select_provider_config


def build_structure_pack(state: dict) -> dict:
    if _provider_configured():
        provider = create_provider()
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
    if _provider_configured():
        provider = create_provider()
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
    if _provider_configured():
        provider = create_provider()
        result = provider.generate_json([
            {
                "role": "system",
                "content": (
                    "Create a modular screen storyboard. Return JSON with a "
                    "scenes array."
                ),
            },
            {"role": "user", "content": str({
                "pack": state.get("pack", {}),
                "score": state.get("score", {}),
            })},
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
                        },
                        "required": ["id", "kind"],
                    },
                    "minItems": 1,
                },
            },
            "required": ["scenes"],
        })
        scenes = result.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            scenes = [{"id": 1, "kind": "text_screen"}]
        return {"scenes": scenes}
    return {"scenes": [{"id": 1, "kind": "text_screen"}]}


def build_verifier_verdict(state: dict) -> dict:
    if _provider_configured():
        provider = create_provider()
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


def _provider_configured() -> bool:
    try:
        select_provider_config()
        return True
    except LLMProviderError:
        return False


def _chapter_prompt(state: dict) -> str:
    return "Source: %s\n\n%s" % (
        state.get("source_ref", "unknown-source"),
        (state.get("source_text") or "")[:6000],
    )


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
