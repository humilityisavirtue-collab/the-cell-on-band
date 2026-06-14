"""config.py — settings from env (handoff §12), with MVP-safe defaults.

Plain os.environ (no pydantic-settings dep). The DB defaults to local async
SQLite so the service runs offline for the demo; handoff §12 names Postgres
(postgresql+asyncpg) for production — swap DATABASE_URL, nothing else changes.
"""
from __future__ import annotations

import os


class Settings:
    APP_ENV: str = os.environ.get("APP_ENV", "dev")
    API_BASE_URL: str = os.environ.get("API_BASE_URL", "http://localhost:8000")
    PUBLIC_SITE_BASE_URL: str = os.environ.get(
        "PUBLIC_SITE_BASE_URL", "http://localhost:8000/public/experiences")
    # MVP: local async sqlite. Prod (handoff §12): postgresql+asyncpg://...
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL", "sqlite+aiosqlite:///./chapterstage.db")
    GENERATED_SITE_ROOT: str = os.environ.get(
        "GENERATED_SITE_ROOT", "./static/generated")
    MAX_UPLOAD_MB: int = int(os.environ.get("MAX_UPLOAD_MB", "20"))
    MAX_CHAPTER_CHARS: int = int(os.environ.get("MAX_CHAPTER_CHARS", "80000"))
    MIN_CHAPTER_CHARS: int = int(os.environ.get("MIN_CHAPTER_CHARS", "500"))
    ALLOWED_UPLOAD_EXT = (".pdf", ".txt")
    VERSION: str = "0.1.0"


settings = Settings()
