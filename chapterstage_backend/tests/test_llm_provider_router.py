"""Phase 4 gate: env-driven LLM provider selection without network calls."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.services.llm.base import JsonMixin, LLMProviderError  # noqa: E402
from app.services.llm.featherless_provider import FeatherlessProvider  # noqa: E402
from app.services.llm.openai_provider import OpenAIProvider  # noqa: E402
from app.services.llm.base import ProviderConfig  # noqa: E402
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
                or key.startswith("LLM_PROVIDER"):
            os.environ.pop(key)


class BadJsonProvider(JsonMixin):
    name = "bad-json"
    model = "bad-json"

    def generate_text(self, messages, model=None, temperature=None,
                      json_schema=None):
        return "I am prose, not JSON."


class FencedJsonProvider(JsonMixin):
    name = "fenced-json"
    model = "fenced-json"

    def generate_text(self, messages, model=None, temperature=None,
                      json_schema=None):
        return '```json\n{"sections": ["intro"], "ideas": ["idea"]}\n```'


class TruncatedJsonProvider(JsonMixin):
    name = "truncated-json"
    model = "truncated-json"

    def generate_text(self, messages, model=None, temperature=None,
                      json_schema=None):
        return '{"sections": ["intro"], "ideas": ["idea"]'


class WrongKeysThenValidProvider(JsonMixin):
    name = "wrong-keys-then-valid"
    model = "wrong-keys-then-valid"

    def __init__(self):
        self.calls = 0

    def generate_text(self, messages, model=None, temperature=None,
                      json_schema=None):
        self.calls += 1
        if self.calls == 1:
            return '{"chapter": "Chapter 1: The Workshop"'
        return '{"sections": ["workshop"], "ideas": ["try a simple machine"]}'


class RetryProvider(OpenAIProvider):
    retry_delays = (0.01,)

    def __init__(self):
        super().__init__(ProviderConfig(
            name="retry-test",
            model="retry-model",
            api_key="test-key",
            base_url="https://example.test/v1",
        ))
        self.slept = []

    def _sleep(self, seconds):
        self.slept.append(seconds)


class FallbackProvider(OpenAIProvider):
    retry_delays = (0.01,)

    def __init__(self):
        super().__init__(ProviderConfig(
            name="fallback-test",
            model="role-model",
            api_key="test-key",
            base_url="https://example.test/v1",
            fallback_model="default-model",
        ))
        self.slept = []

    def _sleep(self, seconds):
        self.slept.append(seconds)


class FakeHttpClient:
    calls = 0
    payloads = []

    def __init__(self, timeout=120):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, headers=None, json=None):
        self.__class__.calls += 1
        self.__class__.payloads.append(json)
        if self.__class__.calls == 1:
            return httpx.Response(
                503,
                request=httpx.Request("POST", url),
                text="no valid executor",
            )
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": "ok"}}]},
        )


class FakeFallbackHttpClient:
    calls = []

    def __init__(self, timeout=120):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, headers=None, json=None):
        model = json["model"]
        self.__class__.calls.append(model)
        if model == "role-model":
            return httpx.Response(
                503,
                request=httpx.Request("POST", url),
                text="no valid executor",
            )
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": "fallback ok"}}]},
        )


STRUCTURE_SCHEMA = {
    "type": "object",
    "required": ["sections", "ideas"],
}


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
    os.environ["FEATHERLESS_API_KEY"] = "fl-test"
    os.environ["FEATHERLESS_MODEL"] = "small-default"
    os.environ["FEATHERLESS_MODEL_STRUCTURE"] = "efficient-structure"
    os.environ["FEATHERLESS_MODEL_VISUAL_BUILDER"] = "large-visual"
    check("role-specific Featherless models override global model",
          select_provider_config("structure").model == "efficient-structure"
          and select_provider_config("structure").fallback_model == "small-default"
          and select_provider_config("visual").model == "large-visual"
          and select_provider_config("visual").fallback_model == "small-default"
          and select_provider_config("verifier").model == "small-default",
          receipt={
              "structure": select_provider_config("structure").model,
              "structure_fallback": select_provider_config("structure").fallback_model,
              "visual": select_provider_config("visual").model,
              "visual_fallback": select_provider_config("visual").fallback_model,
              "verifier": select_provider_config("verifier").model,
          })

    clear_env()
    os.environ["LLM_PROVIDER"] = "ollama"
    os.environ["OLLAMA_MODEL"] = "small-local"
    os.environ["LLM_PROVIDER_VISUAL_BUILDER"] = "openai"
    os.environ["OPENAI_API_KEY"] = "sk-test"
    os.environ["OPENAI_MODEL_VISUAL_BUILDER"] = "large-code"
    check("role-specific provider overrides global provider",
          select_provider_config("structure").name == "ollama"
          and select_provider_config("visual").name == "openai"
          and select_provider_config("visual").model == "large-code",
          receipt={
              "structure": select_provider_config("structure"),
              "visual": select_provider_config("visual"),
          })

    provider = FeatherlessProvider(ProviderConfig(
        name="featherless",
        model="qwen-test",
        api_key="fl-test",
        base_url="https://api.featherless.ai/v1",
    ))
    payload = provider._build_payload(  # noqa: SLF001 - provider contract gate
        [{"role": "user", "content": "return JSON"}],
        None,
        0,
        STRUCTURE_SCHEMA,
    )
    headers = provider._build_headers()  # noqa: SLF001 - provider contract gate
    check("Featherless payload avoids unsupported response_format option",
          payload["model"] == "qwen-test"
          and payload["temperature"] == 0
          and "response_format" not in payload,
          receipt=payload)
    check("Featherless request includes app attribution headers",
          headers["Authorization"] == "Bearer fl-test"
          and headers["HTTP-Referer"]
          and headers["X-Title"] == "ChapterStage",
          receipt=headers)

    import app.services.llm.openai_provider as openai_module  # noqa: E402

    original_client = openai_module.httpx.Client
    FakeHttpClient.calls = 0
    FakeHttpClient.payloads = []
    retry_provider = RetryProvider()
    try:
        openai_module.httpx.Client = FakeHttpClient
        text = retry_provider.generate_text([
            {"role": "user", "content": "hello"},
        ])
    finally:
        openai_module.httpx.Client = original_client
    check("OpenAI-compatible provider retries transient 503 responses",
          text == "ok"
          and FakeHttpClient.calls == 2
          and retry_provider.slept == [0.01],
          receipt={
              "calls": FakeHttpClient.calls,
              "slept": retry_provider.slept,
          })

    original_client = openai_module.httpx.Client
    FakeFallbackHttpClient.calls = []
    fallback_provider = FallbackProvider()
    try:
        openai_module.httpx.Client = FakeFallbackHttpClient
        text = fallback_provider.generate_text([
            {"role": "user", "content": "hello"},
        ])
    finally:
        openai_module.httpx.Client = original_client
    check("provider falls back to default model after repeated service errors",
          text == "fallback ok"
          and FakeFallbackHttpClient.calls
          == ["role-model", "role-model", "default-model"],
          receipt=FakeFallbackHttpClient.calls)

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

    parsed = FencedJsonProvider().generate_json([], STRUCTURE_SCHEMA)
    check("JSON parser accepts fenced provider objects",
          parsed["sections"] == ["intro"] and parsed["ideas"] == ["idea"],
          receipt=parsed)

    parsed = TruncatedJsonProvider().generate_json([], STRUCTURE_SCHEMA)
    check("JSON parser repairs truncated provider objects",
          parsed["sections"] == ["intro"] and parsed["ideas"] == ["idea"],
          receipt=parsed)

    provider = WrongKeysThenValidProvider()
    parsed = provider.generate_json([], STRUCTURE_SCHEMA)
    check("JSON parser retries objects missing required keys",
          provider.calls == 2
          and parsed["sections"] == ["workshop"]
          and parsed["ideas"] == ["try a simple machine"],
          receipt=parsed)

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
