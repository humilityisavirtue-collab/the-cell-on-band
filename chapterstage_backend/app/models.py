"""models.py — SQLModel tables (handoff §8 DB schema).

UUID string PKs (portable across sqlite/postgres). JSON columns for metadata /
payload. M1 exercises books/chapters/generation_jobs; experiences and
agent_trace_events are defined now (cheap) for M2/M5/M6.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Book(SQLModel, table=True):
    __tablename__ = "books"
    id: str = Field(default_factory=_uuid, primary_key=True)
    title: str
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Chapter(SQLModel, table=True):
    __tablename__ = "chapters"
    id: str = Field(default_factory=_uuid, primary_key=True)
    book_id: str = Field(foreign_key="books.id", index=True)
    title: str
    source_type: str            # "text" | "pdf"
    source_text: str | None = None
    source_file_path: str | None = None
    created_at: datetime = Field(default_factory=_now)


class GenerationJob(SQLModel, table=True):
    __tablename__ = "generation_jobs"
    id: str = Field(default_factory=_uuid, primary_key=True)
    chapter_id: str = Field(foreign_key="chapters.id", index=True)
    status: str = "queued"
    audience_level: str = "beginner"
    experience_style: str = "visual_story"
    target_screen_count: int = 6
    enable_auto_brainstorm: bool = True
    band_room_id: str | None = None
    experience_id: str | None = None
    public_url: str | None = None
    progress: float = 0.0
    current_step: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None


class Experience(SQLModel, table=True):
    __tablename__ = "experiences"
    id: str = Field(default_factory=_uuid, primary_key=True)
    job_id: str = Field(foreign_key="generation_jobs.id", index=True)
    public_url: str
    storage_path: str
    meta: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class AgentTraceEvent(SQLModel, table=True):
    __tablename__ = "agent_trace_events"
    id: str = Field(default_factory=_uuid, primary_key=True)
    job_id: str = Field(foreign_key="generation_jobs.id", index=True)
    band_room_id: str | None = None
    agent_name: str
    event_type: str
    title: str
    message: str
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class ReaderProgress(SQLModel, table=True):
    __tablename__ = "reader_progress"
    __table_args__ = (
        UniqueConstraint("experience_id",
                         name="uq_reader_progress_experience"),
    )
    id: str = Field(default_factory=_uuid, primary_key=True)
    experience_id: str = Field(index=True)
    current_screen_id: str | None = None
    completed_screen_ids: list[str] = Field(
        default_factory=list, sa_column=Column(JSON))
    last_checkpoint: str | None = None
    interaction_state: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
