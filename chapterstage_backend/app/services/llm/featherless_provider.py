"""Featherless OpenAI-compatible provider."""
from __future__ import annotations

from .base import ProviderConfig
from .openai_provider import OpenAIProvider


class FeatherlessProvider(OpenAIProvider):
    name = "featherless"

    def __init__(self, config: ProviderConfig):
        super().__init__(ProviderConfig(
            name="featherless",
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url or "https://api.featherless.ai/v1",
        ))
