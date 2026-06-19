"""Config gate: chapterstage_backend/.env autoloads without clobbering exports."""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

FAILURES: list[str] = []
RAN: list[str] = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


def _clear_env():
    for key in (
            "CHAPTERSTAGE_ENV_FILE", "APP_ENV", "LLM_PROVIDER", "OLLAMA_MODEL",
            "OLLAMA_BASE_URL", "PUBLIC_SITE_BASE_URL"):
        os.environ.pop(key, None)


def main():
    print("test_config_env_loading.py — .env autoload")
    _clear_env()
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    env_file = Path(tmp.name) / ".env"
    env_file.write_text(
        "LLM_PROVIDER=ollama\n"
        "OLLAMA_MODEL=qwen2.5:3b\n"
        "OLLAMA_BASE_URL=http://127.0.0.1:11434\n"
        "PUBLIC_SITE_BASE_URL='http://127.0.0.1:8000/public/experiences'\n",
        encoding="utf-8",
    )
    os.environ["CHAPTERSTAGE_ENV_FILE"] = str(env_file)
    config = importlib.import_module("app.config")
    config = importlib.reload(config)
    check("custom .env file autoloads before settings init",
          config.settings.LLM_PROVIDER == "ollama"
          and config.settings.OLLAMA_MODEL == "qwen2.5:3b"
          and config.settings.OLLAMA_BASE_URL == "http://127.0.0.1:11434",
          receipt="provider=%r model=%r base=%r" % (
              config.settings.LLM_PROVIDER,
              config.settings.OLLAMA_MODEL,
              config.settings.OLLAMA_BASE_URL,
          ))
    check("quoted .env values are unwrapped",
          config.settings.PUBLIC_SITE_BASE_URL
          == "http://127.0.0.1:8000/public/experiences",
          receipt=config.settings.PUBLIC_SITE_BASE_URL)

    os.environ["OLLAMA_MODEL"] = "exported-model"
    config.load_env_file(env_file)
    check("exported env vars keep priority over .env defaults",
          os.environ["OLLAMA_MODEL"] == "exported-model",
          receipt=os.environ["OLLAMA_MODEL"])

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — backend autoloads .env and still respects exported env "
          "overrides.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
