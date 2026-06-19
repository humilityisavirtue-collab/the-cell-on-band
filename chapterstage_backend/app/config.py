"""config.py — settings from env (handoff §12), with MVP-safe defaults.

The backend auto-loads `chapterstage_backend/.env` into `os.environ` on import,
without overriding variables that were already exported in the shell. The DB
defaults to local async SQLite so the service runs offline for the demo; handoff
§12 names Postgres (postgresql+asyncpg) for production — swap DATABASE_URL,
nothing else changes.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | Path, override: bool = False) -> None:
    """Load KEY=VALUE lines into os.environ.

    Existing exported env vars win by default so shell-level overrides remain the
    highest-priority configuration source.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value


_DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_env_file(os.environ.get("CHAPTERSTAGE_ENV_FILE", _DEFAULT_ENV_FILE))


class Settings:
    def __init__(self):
        self.APP_ENV: str = os.environ.get("APP_ENV", "dev")
        self.API_BASE_URL: str = os.environ.get(
            "API_BASE_URL", "http://localhost:8000")
        self.PUBLIC_SITE_BASE_URL: str = os.environ.get(
            "PUBLIC_SITE_BASE_URL", "http://localhost:8000/public/experiences")
        # MVP: local async sqlite. Prod (handoff §12): postgresql+asyncpg://...
        self.DATABASE_URL: str = os.environ.get(
            "DATABASE_URL", "sqlite+aiosqlite:///./chapterstage.db")
        self.GENERATED_SITE_ROOT: str = os.environ.get(
            "GENERATED_SITE_ROOT", "./static/generated")
        self.MAX_UPLOAD_MB: int = int(os.environ.get("MAX_UPLOAD_MB", "20"))
        self.MAX_CHAPTER_CHARS: int = int(
            os.environ.get("MAX_CHAPTER_CHARS", "80000"))
        self.MIN_CHAPTER_CHARS: int = int(
            os.environ.get("MIN_CHAPTER_CHARS", "500"))
        self.ALLOWED_UPLOAD_EXT = (".pdf", ".txt")

        # Band transport selection. `test` is offline and deterministic; `live`
        # is the only mode allowed to import/call the Band SDK.
        self.BAND_TRANSPORT_MODE: str = os.environ.get(
            "BAND_TRANSPORT_MODE", "test")
        self.BAND_API_KEY: str = os.environ.get("BAND_API_KEY", "")
        self.BAND_API_URL: str = os.environ.get(
            "BAND_API_URL",
            os.environ.get("BAND_REST_URL", "https://app.band.ai"))
        self.BAND_WS_URL: str = os.environ.get(
            "BAND_WS_URL", "wss://app.band.ai/api/v1/socket/websocket")
        self.BAND_ROOM_URL_TEMPLATE: str = os.environ.get(
            "BAND_ROOM_URL_TEMPLATE", "")
        self.BAND_AGENT_UUID_COORDINATOR: str = os.environ.get(
            "BAND_AGENT_UUID_COORDINATOR", "")
        self.BAND_AGENT_UUID_STRUCTURE: str = os.environ.get(
            "BAND_AGENT_UUID_STRUCTURE", "")
        self.BAND_AGENT_UUID_PEDAGOGY: str = os.environ.get(
            "BAND_AGENT_UUID_PEDAGOGY", "")
        self.BAND_AGENT_UUID_BRAINSTORM: str = os.environ.get(
            "BAND_AGENT_UUID_BRAINSTORM", "")
        self.BAND_AGENT_UUID_VISUAL_BUILDER: str = os.environ.get(
            "BAND_AGENT_UUID_VISUAL_BUILDER", "")
        self.BAND_AGENT_UUID_VERIFIER: str = os.environ.get(
            "BAND_AGENT_UUID_VERIFIER", "")

        self.LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "auto")
        self.OLLAMA_BASE_URL: str = os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434")
        self.OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "")
        self.OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
        self.OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "")
        self.OPENAI_BASE_URL: str = os.environ.get(
            "OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
        self.ANTHROPIC_MODEL: str = os.environ.get("ANTHROPIC_MODEL", "")
        self.FEATHERLESS_API_KEY: str = os.environ.get("FEATHERLESS_API_KEY", "")
        self.FEATHERLESS_MODEL: str = os.environ.get("FEATHERLESS_MODEL", "")
        self.FEATHERLESS_BASE_URL: str = os.environ.get(
            "FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1")

        self.LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
        self.VERSION: str = "0.1.0"


settings = Settings()
