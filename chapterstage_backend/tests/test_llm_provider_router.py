"""Phase 4 gate: env-driven LLM provider selection without network calls."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.services.llm.base import JsonMixin, LLMProviderError  # noqa: E402
from app.services.llm.router import create_provider, select_provider_config  # noqa: E402

FAILURES: list[str] = []
RAN: list[str] = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


def clear_env():
    for key in list(os.environ):
        if key.startswith(("OLLAMA_", "OPENAI_", "ANTHROPIC_", "FEATHERLESS_")) \
                or key == "LLM_PROVIDER":
            os.environ.pop(key)


class BadJsonProvider(JsonMixin):
    name = "bad-json"
    model = "bad-json"

    def generate_text(self, messages, model=None, temperature=None,
                      json_schema=None):
        return "I am prose, not JSON."


def main():
    print("test_llm_provider_router.py — provider selection")
    clear_env()
    failed = False
    try:
        select_provider_config()
    except LLMProviderError:
        failed = True
    check("auto mode fails clearly with no provider env", failed)

    clear_env()
    os.environ["OLLAMA_MODEL"] = "llama3.1"
    cfg = select_provider_config()
    provider = create_provider()
    check("auto mode prefers configured Ollama",
          cfg.name == "ollama" and provider.name == "ollama"
          and provider.model == "llama3.1", receipt=cfg)

    clear_env()
    os.environ["OPENAI_API_KEY"] = "sk-test"
    os.environ["OPENAI_MODEL"] = "gpt-test"
    cfg = select_provider_config()
    check("OpenAI selected when only OpenAI env is set",
          cfg.name == "openai" and cfg.model == "gpt-test", receipt=cfg)

    clear_env()
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
    os.environ["ANTHROPIC_MODEL"] = "claude-test"
    cfg = select_provider_config()
    check("Anthropic selected when Claude env is set",
          cfg.name == "anthropic" and cfg.model == "claude-test", receipt=cfg)

    clear_env()
    os.environ["FEATHERLESS_API_KEY"] = "fl-test"
    os.environ["FEATHERLESS_MODEL"] = "qwen-test"
    cfg = select_provider_config()
    check("Featherless selected when Featherless env is set",
          cfg.name == "featherless" and cfg.model == "qwen-test", receipt=cfg)

    clear_env()
    os.environ["LLM_PROVIDER"] = "openai"
    failed = False
    try:
        select_provider_config()
    except LLMProviderError as exc:
        failed = "missing required env values" in str(exc)
    check("explicit provider fails fast when env is incomplete", failed)

    failed = False
    try:
        BadJsonProvider().generate_json([], {})
    except LLMProviderError as exc:
        failed = ("Provider returned invalid JSON" in str(exc)
                  and "I am prose, not JSON." in str(exc))
    check("invalid provider JSON error includes response preview", failed)

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — provider selection is env-driven, local-first, and "
          "network-free until generation is called.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
