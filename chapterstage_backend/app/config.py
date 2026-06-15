"""config.py — settings from env (handoff §12), with MVP-safe defaults.

Plain os.environ (no pydantic-settings dep). The DB defaults to local async
SQLite so the service runs offline for the demo; handoff §12 names Postgres
(postgresql+asyncpg) for production — swap DATABASE_URL, nothing else changes.
"""
from __future__ import annotations

import os


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

        self.VERSION: str = "0.1.0"


settings = Settings()
