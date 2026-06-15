"""Anthropic Claude provider."""
from __future__ import annotations

import httpx

from .base import ChatMessage, JsonMixin, LLMProviderError, ProviderConfig


class AnthropicProvider(JsonMixin):
    name = "anthropic"

    def __init__(self, config: ProviderConfig):
        self.model = config.model
        self.api_key = config.api_key
        self.base_url = (config.base_url or "https://api.anthropic.com").rstrip("/")

    def generate_text(
            self, messages: list[ChatMessage], model: str | None = None,
            temperature: float | None = None,
            json_schema: dict | None = None) -> str:
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        user_messages = [
            {"role": m["role"] if m["role"] in ("user", "assistant") else "user",
             "content": m["content"]}
            for m in messages if m["role"] != "system"
        ]
        if json_schema is not None:
            user_messages.append({
                "role": "user",
                "content": "Return only valid JSON matching the requested schema.",
            })
        payload = {
            "model": model or self.model,
            "max_tokens": 4096,
            "messages": user_messages or [{"role": "user", "content": ""}],
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if temperature is not None:
            payload["temperature"] = temperature
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        try:
            with httpx.Client(timeout=120) as client:
                response = client.post(
                    "%s/v1/messages" % self.base_url,
                    headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMProviderError("Anthropic generation failed: %s" % exc) from exc
        data = response.json()
        blocks = data.get("content") or []
        return "".join(block.get("text", "") for block in blocks)
