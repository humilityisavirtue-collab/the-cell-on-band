"""OpenAI-compatible chat completions provider."""
from __future__ import annotations

import httpx

from .base import ChatMessage, JsonMixin, LLMProviderError, ProviderConfig


class OpenAIProvider(JsonMixin):
    name = "openai"

    def __init__(self, config: ProviderConfig):
        self.model = config.model
        self.api_key = config.api_key
        self.base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")

    def generate_text(
            self, messages: list[ChatMessage], model: str | None = None,
            temperature: float | None = None,
            json_schema: dict | None = None) -> str:
        payload = {"model": model or self.model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if json_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": "Bearer %s" % self.api_key}
        try:
            with httpx.Client(timeout=120) as client:
                response = client.post(
                    "%s/chat/completions" % self.base_url,
                    headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMProviderError("OpenAI generation failed: %s" % exc) from exc
        data = response.json()
        return data["choices"][0]["message"]["content"]
