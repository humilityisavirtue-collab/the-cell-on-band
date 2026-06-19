"""Featherless OpenAI-compatible provider."""
from __future__ import annotations

import os

from .base import ProviderConfig
from .openai_provider import OpenAIProvider


class FeatherlessProvider(OpenAIProvider):
    name = "featherless"
    supports_json_response_format = False

    def __init__(self, config: ProviderConfig):
        super().__init__(ProviderConfig(
            name="featherless",
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url or "https://api.featherless.ai/v1",
        ))

    def _build_headers(self) -> dict[str, str]:
        headers = super()._build_headers()
        referer = os.environ.get("FEATHERLESS_HTTP_REFERER") \
            or os.environ.get("API_BASE_URL") \
            or "http://localhost"
        title = os.environ.get("FEATHERLESS_APP_TITLE") or "ChapterStage"
        headers["HTTP-Referer"] = referer
        headers["X-Title"] = title
        return headers
