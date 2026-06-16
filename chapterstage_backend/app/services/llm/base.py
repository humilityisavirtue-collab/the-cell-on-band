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
        text = self.generate_text(messages, model=model, json_schema=schema)  # type: ignore[attr-defined]
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            preview = " ".join((text or "").split())[:500]
            detail = " Preview: %r" % preview if preview else ""
            raise LLMProviderError(
                "Provider returned invalid JSON.%s" % detail) from exc
