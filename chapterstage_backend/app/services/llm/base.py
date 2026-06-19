"""Shared LLM provider contracts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol, TypedDict


class LLMProviderError(RuntimeError):
    """Raised for provider configuration or generation failures."""


class ChatMessage(TypedDict):
    role: str
    content: str


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    api_key: str = ""
    base_url: str = ""
    fallback_model: str = ""


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_text(
            self, messages: list[ChatMessage], model: str | None = None,
            temperature: float | None = None,
            json_schema: dict | None = None) -> str:
        ...

    def generate_json(
            self, messages: list[ChatMessage], schema: dict,
            model: str | None = None) -> dict:
        ...


class JsonMixin:
    def generate_json(
            self, messages: list[ChatMessage], schema: dict,
            model: str | None = None) -> dict:
        json_messages = _with_json_instruction(messages, schema)
        text = ""
        first_error: Exception | None = None
        try:
            text = self.generate_text(  # type: ignore[attr-defined]
                json_messages, model=model, temperature=0, json_schema=schema)
            return _parse_json_object(text, schema)
        except (json.JSONDecodeError, LLMProviderError) as exc:
            first_error = exc

        retry_messages = list(json_messages)
        if text:
            retry_messages.append({
                "role": "assistant",
                "content": text[:4000],
            })
        retry_messages.append({
            "role": "user",
            "content": (
                "The previous response was not valid parseable JSON. "
                "Return only a corrected JSON object. Do not include prose, "
                "markdown fences, comments, or trailing text."
            ),
        })
        retry_text = ""
        try:
            retry_text = self.generate_text(  # type: ignore[attr-defined]
                retry_messages, model=model, temperature=0, json_schema=schema)
            return _parse_json_object(retry_text, schema)
        except (json.JSONDecodeError, LLMProviderError) as exc:
            preview = _preview(retry_text or text)
            detail = " Preview: %r" % preview if preview else ""
            raise LLMProviderError(
                "Provider returned invalid JSON.%s" % detail) from (first_error or exc)


def _with_json_instruction(
        messages: list[ChatMessage], schema: dict) -> list[ChatMessage]:
    instructed = list(messages)
    instructed.append({
        "role": "user",
        "content": _json_instruction(schema),
    })
    return instructed


def _json_instruction(schema: dict) -> str:
    required = schema.get("required") or []
    required_text = ", ".join(str(key) for key in required) or "none"
    schema_text = json.dumps(schema, sort_keys=True)
    return (
        "Return only one valid JSON object matching this JSON Schema. "
        "Required keys: %s. Do not include markdown fences, explanations, "
        "comments, or trailing text.\n\nJSON Schema:\n%s"
        % (required_text, schema_text[:3000])
    )


def _parse_json_object(text: str, schema: dict | None = None) -> dict:
    candidates = _json_candidates(text)
    last_error = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(parsed, dict):
            last_error = json.JSONDecodeError(
                "Expected JSON object", candidate, 0)
            continue
        missing = _missing_required_keys(parsed, schema)
        if missing:
            last_error = json.JSONDecodeError(
                "Missing required JSON keys: %s" % ", ".join(missing),
                candidate, 0)
            continue
        return parsed
    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("No JSON content", text or "", 0)


def _json_candidates(text: str) -> list[str]:
    raw = text or ""
    stripped = raw.strip()
    candidates: list[str] = []
    for candidate in (
            stripped,
            _strip_markdown_fence(stripped),
            _extract_first_json(stripped),
            _repair_truncated_json(stripped),
    ):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _missing_required_keys(parsed: dict, schema: dict | None) -> list[str]:
    if not schema:
        return []
    required = schema.get("required") or []
    return [str(key) for key in required if key not in parsed]


def _strip_markdown_fence(text: str) -> str | None:
    if not text.startswith("```"):
        return None
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_first_json(text: str) -> str | None:
    pairs = {"{": "}", "[": "]"}
    for start, char in enumerate(text):
        if char not in pairs:
            continue
        stack = [pairs[char]]
        in_string = False
        escaped = False
        for index in range(start + 1, len(text)):
            current = text[index]
            if escaped:
                escaped = False
                continue
            if current == "\\" and in_string:
                escaped = True
                continue
            if current == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if current in pairs:
                stack.append(pairs[current])
                continue
            if stack and current == stack[-1]:
                stack.pop()
                if not stack:
                    return text[start:index + 1]
    return None


def _repair_truncated_json(text: str) -> str | None:
    start = min(
        [idx for idx in (text.find("{"), text.find("[")) if idx >= 0],
        default=-1,
    )
    if start < 0:
        return None
    candidate = text[start:].strip()
    pairs = {"{": "}", "[": "]"}
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in candidate:
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in pairs:
            stack.append(pairs[char])
            continue
        if stack and char == stack[-1]:
            stack.pop()
    if not stack and not in_string:
        return None
    repaired = candidate
    if escaped:
        repaired += "\\"
    if in_string:
        repaired += '"'
    repaired += "".join(reversed(stack))
    return repaired


def _preview(text: str) -> str:
    return " ".join((text or "").split())[:500]
