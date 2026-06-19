"""database.py — async SQLModel engine + session dependency (handoff §8).

Async SQLAlchemy/SQLModel on the configured DATABASE_URL. init_db() creates
tables (MVP; production would use migrations). get_session is the FastAPI
dependency yielding an AsyncSession per request.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    # import models so SQLModel.metadata is populated before create_all
    import app.models  # noqa: F401
    async with engine.begin() as conn:
        migrated_reader_progress = await _migrate_global_reader_progress(conn)
        await conn.run_sync(SQLModel.metadata.create_all)
        await _ensure_generation_jobs_cancel_column(conn)
        await _ensure_agent_trace_events_elapsed_seconds_column(conn)
        if migrated_reader_progress:
            await conn.execute(text("""
                INSERT OR IGNORE INTO reader_progress (
                    id, experience_id, current_screen_id, completed_screen_ids,
                    last_checkpoint, interaction_state, created_at, updated_at
                )
                SELECT
                    id, experience_id, current_screen_id, completed_screen_ids,
                    last_checkpoint, interaction_state, created_at, updated_at
                FROM reader_progress_user_scoped_backup
                ORDER BY updated_at DESC
            """))


async def _migrate_global_reader_progress(conn) -> bool:
    """Fold the brief user-scoped SQLite table into one row per experience."""
    if conn.dialect.name != "sqlite":
        return False
    exists = (await conn.execute(text(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='reader_progress'"
    ))).scalar_one_or_none()
    if not exists:
        return False
    columns = (await conn.execute(
        text("PRAGMA table_info(reader_progress)"))).fetchall()
    column_names = {row[1] for row in columns}
    if "user_id" not in column_names:
        return False
    await conn.execute(text("DROP TABLE IF EXISTS reader_progress_user_scoped_backup"))
    await conn.execute(text(
        "ALTER TABLE reader_progress RENAME TO reader_progress_user_scoped_backup"))
    return True


async def _ensure_generation_jobs_cancel_column(conn) -> None:
    """Add cancellation metadata to existing local SQLite dev databases."""
    if conn.dialect.name != "sqlite":
        return
    exists = (await conn.execute(text(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='generation_jobs'"
    ))).scalar_one_or_none()
    if not exists:
        return
    columns = (await conn.execute(
        text("PRAGMA table_info(generation_jobs)"))).fetchall()
    column_names = {row[1] for row in columns}
    if "cancel_requested_at" not in column_names:
        await conn.execute(text(
            "ALTER TABLE generation_jobs ADD COLUMN cancel_requested_at DATETIME"))


async def _ensure_agent_trace_events_elapsed_seconds_column(conn) -> None:
    """Add elapsed timer column to existing agent trace event tables."""
    if conn.dialect.name != "sqlite":
        return
    exists = (await conn.execute(text(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='agent_trace_events'"
    ))).scalar_one_or_none()
    if not exists:
        return
    columns = (await conn.execute(
        text("PRAGMA table_info(agent_trace_events)"))).fetchall()
    column_names = {row[1] for row in columns}
    if "elapsed_seconds" not in column_names:
        await conn.execute(text(
            "ALTER TABLE agent_trace_events ADD COLUMN elapsed_seconds INTEGER"))


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
