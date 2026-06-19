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
            payload["format"] = json_schema
        try:
            with httpx.Client(timeout=120) as client:
                response = _post_chat(client, self.base_url, payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if json_schema is not None and payload.get("format") != "json":
                payload["format"] = "json"
                try:
                    with httpx.Client(timeout=120) as client:
                        response = _post_chat(client, self.base_url, payload)
                        response.raise_for_status()
                except httpx.HTTPError as fallback_exc:
                    raise LLMProviderError(
                        "Ollama generation failed: %s" % fallback_exc
                    ) from fallback_exc
            else:
                raise LLMProviderError(
                    "Ollama generation failed: %s" % exc) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError("Ollama generation failed: %s" % exc) from exc
        data = response.json()
        return data.get("message", {}).get("content", "")


def _post_chat(client: httpx.Client, base_url: str, payload: dict) -> httpx.Response:
    return client.post("%s/api/chat" % base_url, json=payload)
