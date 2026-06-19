"""Environment-driven provider selection."""
from __future__ import annotations

import os

from .anthropic_provider import AnthropicProvider
from .base import LLMProviderError, ProviderConfig
from .featherless_provider import FeatherlessProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider


def select_provider_config(role: str | None = None) -> ProviderConfig:
    requested = (_env("LLM_PROVIDER", role) or "auto").strip().lower()
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
        config = candidates[requested](role)
        if config is None:
            raise LLMProviderError(
                "LLM_PROVIDER=%s is missing required env values." % requested)
        return config

    for build in (_ollama_config, _openai_config, _anthropic_config,
                  _featherless_config):
        config = build(role)
        if config is not None:
            return config
    raise LLMProviderError(
        "No LLM provider configured. Set OLLAMA_MODEL, OPENAI_API_KEY, "
        "ANTHROPIC_API_KEY, or FEATHERLESS_API_KEY.")


def create_provider(role: str | None = None):
    config = select_provider_config(role)
    if config.name == "ollama":
        return OllamaProvider(config)
    if config.name == "openai":
        return OpenAIProvider(config)
    if config.name == "anthropic":
        return AnthropicProvider(config)
    if config.name == "featherless":
        return FeatherlessProvider(config)
    raise LLMProviderError("Unsupported provider %r." % config.name)


def _ollama_config(role: str | None = None) -> ProviderConfig | None:
    role_model = _role_env("OLLAMA_MODEL", role).strip()
    global_model = os.environ.get("OLLAMA_MODEL", "").strip()
    model = role_model or global_model
    if not model:
        return None
    return ProviderConfig(
        name="ollama", model=model,
        base_url=_env("OLLAMA_BASE_URL", role, "http://localhost:11434"),
        fallback_model=_fallback_model(role_model, global_model))


def _openai_config(role: str | None = None) -> ProviderConfig | None:
    key = _env("OPENAI_API_KEY", role).strip()
    role_model = _role_env("OPENAI_MODEL", role).strip()
    global_model = os.environ.get("OPENAI_MODEL", "").strip()
    model = role_model or global_model
    if not key or not model:
        return None
    return ProviderConfig(
        name="openai", model=model, api_key=key,
        base_url=_env("OPENAI_BASE_URL", role, "https://api.openai.com/v1"),
        fallback_model=_fallback_model(role_model, global_model))


def _anthropic_config(role: str | None = None) -> ProviderConfig | None:
    key = _env("ANTHROPIC_API_KEY", role).strip()
    role_model = _role_env("ANTHROPIC_MODEL", role).strip()
    global_model = os.environ.get("ANTHROPIC_MODEL", "").strip()
    model = role_model or global_model
    if not key or not model:
        return None
    return ProviderConfig(
        name="anthropic", model=model, api_key=key,
        base_url=_env("ANTHROPIC_BASE_URL", role, "https://api.anthropic.com"),
        fallback_model=_fallback_model(role_model, global_model))


def _featherless_config(role: str | None = None) -> ProviderConfig | None:
    key = _env("FEATHERLESS_API_KEY", role).strip()
    role_model = _role_env("FEATHERLESS_MODEL", role).strip()
    global_model = os.environ.get("FEATHERLESS_MODEL", "").strip()
    model = role_model or global_model
    if not key or not model:
        return None
    return ProviderConfig(
        name="featherless", model=model, api_key=key,
        base_url=_env(
            "FEATHERLESS_BASE_URL", role, "https://api.featherless.ai/v1"),
        fallback_model=_fallback_model(role_model, global_model))


def _env(name: str, role: str | None = None, default: str = "") -> str:
    value = _role_env(name, role)
    if value:
        return value
    return os.environ.get(name, default)


def _role_env(name: str, role: str | None = None) -> str:
    for suffix in _role_suffixes(role):
        value = os.environ.get("%s_%s" % (name, suffix), "").strip()
        if value:
            return value
    return ""


def _fallback_model(role_model: str, global_model: str) -> str:
    if role_model and global_model and role_model != global_model:
        return global_model
    return ""


def _role_suffixes(role: str | None) -> list[str]:
    if not role:
        return []
    normalized = role.strip().upper().replace("-", "_")
    aliases = {
        "VISUAL": ["VISUAL_BUILDER", "VISUAL"],
        "VISUAL_BUILDER": ["VISUAL_BUILDER", "VISUAL"],
    }
    return aliases.get(normalized, [normalized])
