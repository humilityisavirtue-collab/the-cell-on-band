"""OpenAI-compatible chat completions provider."""
from __future__ import annotations

import time

import httpx

from .base import ChatMessage, JsonMixin, LLMProviderError, ProviderConfig


class OpenAIProvider(JsonMixin):
    name = "openai"
    retry_statuses = {429, 500, 502, 503, 504}
    fallback_statuses = {500, 502, 503, 504}
    retry_delays = (1.0, 3.0, 6.0)
    supports_json_response_format = True

    def __init__(self, config: ProviderConfig):
        self.name = config.name or self.name
        self.model = config.model
        self.fallback_model = config.fallback_model
        self.api_key = config.api_key
        self.base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")

    def generate_text(
            self, messages: list[ChatMessage], model: str | None = None,
            temperature: float | None = None,
            json_schema: dict | None = None) -> str:
        payload = self._build_payload(messages, model, temperature, json_schema)
        response = self._post_with_retries(payload, self._build_headers())
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _build_payload(
            self, messages: list[ChatMessage], model: str | None,
            temperature: float | None, json_schema: dict | None) -> dict:
        payload = {"model": model or self.model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if json_schema is not None and self.supports_json_response_format:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _build_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer %s" % self.api_key}

    def _post_with_retries(
            self, payload: dict, headers: dict[str, str],
            allow_fallback: bool = True) -> httpx.Response:
        attempts = len(self.retry_delays) + 1
        with httpx.Client(timeout=120) as client:
            for attempt in range(attempts):
                try:
                    response = client.post(
                        "%s/chat/completions" % self.base_url,
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    return response
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if status not in self.retry_statuses or attempt >= attempts - 1:
                        if allow_fallback and self._can_fallback(status, payload):
                            fallback_payload = dict(payload)
                            fallback_payload["model"] = self.fallback_model
                            return self._post_with_retries(
                                fallback_payload, headers, allow_fallback=False)
                        raise self._provider_error(exc, payload) from exc
                    self._sleep(self.retry_delays[attempt])
                except httpx.RequestError as exc:
                    if attempt >= attempts - 1:
                        raise self._provider_error(exc, payload) from exc
                    self._sleep(self.retry_delays[attempt])
        raise self._provider_error(None, payload)

    def _can_fallback(self, status: int, payload: dict) -> bool:
        model = str(payload.get("model") or "")
        return (
            status in self.fallback_statuses
            and bool(self.fallback_model)
            and model != self.fallback_model
        )

    def _provider_error(
            self, exc: httpx.HTTPError | None, payload: dict) -> LLMProviderError:
        model = str(payload.get("model") or self.model)
        if isinstance(exc, httpx.HTTPStatusError):
            response = exc.response
            body = response.text[:500] if response.text else ""
            detail = "HTTP %s" % response.status_code
            if body:
                detail += " body=%r" % body
            return LLMProviderError(
                "%s generation failed for model %s: %s" % (
                    self.name, model, detail))
        return LLMProviderError(
            "%s generation failed for model %s: %s" % (
                self.name, model, exc or "unknown error"))

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)
