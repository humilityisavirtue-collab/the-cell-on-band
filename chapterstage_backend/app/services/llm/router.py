"""Environment-driven provider selection."""
from __future__ import annotations

import os

from .anthropic_provider import AnthropicProvider
from .base import LLMProviderError, ProviderConfig
from .featherless_provider import FeatherlessProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider


def select_provider_config() -> ProviderConfig:
    requested = (os.environ.get("LLM_PROVIDER") or "auto").strip().lower()
    candidates = {
        "ollama": _ollama_config,
        "openai": _openai_config,
        "anthropic": _anthropic_config,
        "claude": _anthropic_config,
        "featherless": _featherless_config,
    }
    if requested != "auto":
        if requested not in candidates:
            raise LLMProviderError("Unknown LLM_PROVIDER %r." % requested)
        config = candidates[requested]()
        if config is None:
            raise LLMProviderError(
                "LLM_PROVIDER=%s is missing required env values." % requested)
        return config

    for build in (_ollama_config, _openai_config, _anthropic_config,
                  _featherless_config):
        config = build()
        if config is not None:
            return config
    raise LLMProviderError(
        "No LLM provider configured. Set OLLAMA_MODEL, OPENAI_API_KEY, "
        "ANTHROPIC_API_KEY, or FEATHERLESS_API_KEY.")


def create_provider():
    config = select_provider_config()
    if config.name == "ollama":
        return OllamaProvider(config)
    if config.name == "openai":
        return OpenAIProvider(config)
    if config.name == "anthropic":
        return AnthropicProvider(config)
    if config.name == "featherless":
        return FeatherlessProvider(config)
    raise LLMProviderError("Unsupported provider %r." % config.name)


def _ollama_config() -> ProviderConfig | None:
    model = os.environ.get("OLLAMA_MODEL", "").strip()
    if not model:
        return None
    return ProviderConfig(
        name="ollama", model=model,
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"))


def _openai_config() -> ProviderConfig | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip()
    if not key or not model:
        return None
    return ProviderConfig(
        name="openai", model=model, api_key=key,
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))


def _anthropic_config() -> ProviderConfig | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = os.environ.get("ANTHROPIC_MODEL", "").strip()
    if not key or not model:
        return None
    return ProviderConfig(
        name="anthropic", model=model, api_key=key,
        base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"))


def _featherless_config() -> ProviderConfig | None:
    key = os.environ.get("FEATHERLESS_API_KEY", "").strip()
    model = os.environ.get("FEATHERLESS_MODEL", "").strip()
    if not key or not model:
        return None
    return ProviderConfig(
        name="featherless", model=model, api_key=key,
        base_url=os.environ.get(
            "FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1"))
