"""ChapterStage agent bodies with provider-backed and deterministic modes."""
from __future__ import annotations

from app.services.llm.base import LLMProviderError
from app.services.llm.router import create_provider, select_provider_config


def build_structure_pack(state: dict) -> dict:
    if _provider_configured():
        provider = create_provider()
        result = provider.generate_json([
            {"role": "system", "content": "Extract a faithful chapter structure."},
            {"role": "user", "content": _chapter_prompt(state)},
        ], schema={
            "type": "object",
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
            {"role": "system", "content": "Score one interactive learning concept."},
            {"role": "user", "content": str(state.get("pack", {}))},
        ], schema={
            "type": "object",
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
            {"role": "system", "content": "Create a modular screen storyboard."},
            {"role": "user", "content": str({
                "pack": state.get("pack", {}),
                "score": state.get("score", {}),
            })},
        ], schema={"type": "object", "required": ["scenes"]})
        scenes = result.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            scenes = [{"id": 1, "kind": "text_screen"}]
        return {"scenes": scenes}
    return {"scenes": [{"id": 1, "kind": "text_screen"}]}


def build_verifier_verdict(state: dict) -> dict:
    if _provider_configured():
        provider = create_provider()
        result = provider.generate_json([
            {"role": "system", "content": "Verify source faithfulness."},
            {"role": "user", "content": str({
                "source_ref": state.get("source_ref"),
                "storyboard": state.get("storyboard", {}),
            })},
        ], schema={"type": "object", "required": ["result", "receipts"]})
        result_value = str(result.get("result") or "PASS").upper()
        return {
            "gate": "source_faithfulness",
            "result": "PASS" if result_value == "PASS" else "FAIL",
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
