"""Ollama local provider."""
from __future__ import annotations

import httpx

from .base import ChatMessage, JsonMixin, LLMProviderError, ProviderConfig


class OllamaProvider(JsonMixin):
    name = "ollama"

    def __init__(self, config: ProviderConfig):
        self.model = config.model
        self.base_url = (config.base_url or "http://localhost:11434").rstrip("/")

    def generate_text(
            self, messages: list[ChatMessage], model: str | None = None,
            temperature: float | None = None,
            json_schema: dict | None = None) -> str:
        payload = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
        }
        if temperature is not None:
            payload["options"] = {"temperature": temperature}
        if json_schema is not None:
            payload["format"] = "json"
        try:
            with httpx.Client(timeout=120) as client:
                response = client.post("%s/api/chat" % self.base_url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMProviderError("Ollama generation failed: %s" % exc) from exc
        data = response.json()
        return data.get("message", {}).get("content", "")
