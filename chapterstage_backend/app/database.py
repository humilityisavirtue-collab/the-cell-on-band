"""database.py — async SQLModel engine + session dependency (handoff §8).

Async SQLAlchemy/SQLModel on the configured DATABASE_URL. init_db() creates
tables (MVP; production would use migrations). get_session is the FastAPI
dependency yielding an AsyncSession per request.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    # import models so SQLModel.metadata is populated before create_all
    import app.models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
