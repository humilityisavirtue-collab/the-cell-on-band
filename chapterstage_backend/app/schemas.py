"""schemas.py — Pydantic DTOs, shapes VERBATIM from handoff §9 (frontend contract).

PROVISIONAL: spade transcribed §9 from Kit's Discord paste; these shapes are NOT
locked until Kit diff-checks the transcription (no frontend drift allowed). Field
names here mirror §9 exactly so the KMP client deserializes without surprise.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

AudienceLevel = Literal["beginner", "intermediate", "expert"]
ExperienceStyle = Literal[
    "visual_story", "lecture_mode", "concept_map_first", "quiz_first", "case_study"]


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


class UserResponse(BaseModel):
    user_id: str
    email: str
    created_at: datetime


class AuthRegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=200)


class AuthLoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# § 9.2 POST /chapters/text
class ChapterTextRequest(BaseModel):
    book_title: Optional[str] = None
    chapter_title: Optional[str] = None
    text: str


# § 9.2 / 9.3 response
class ChapterResponse(BaseModel):
    chapter_id: str
    book_id: str
    title: str
    source_type: str
    created_at: datetime


# § 9.4 POST /generation-jobs
class JobCreateRequest(BaseModel):
    chapter_id: str
    audience_level: AudienceLevel = "beginner"
    experience_style: ExperienceStyle = "visual_story"
    target_screen_count: int = Field(default=6, ge=1, le=50)
    enable_auto_brainstorm: bool = True


class JobCreateResponse(BaseModel):
    job_id: str
    chapter_id: str
    status: str
    status_url: str
    events_url: str


# § 9.5 GET /generation-jobs/{id}
class JobStatusResponse(BaseModel):
    job_id: str
    chapter_id: str
    status: str
    progress: float
    current_step: Optional[str] = None
    band_room_id: Optional[str] = None
    experience_id: Optional[str] = None
    public_url: Optional[str] = None
    error: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class ReaderProgressUpdate(BaseModel):
    current_screen_id: Optional[str] = None
    completed_screen_ids: list[str] = Field(default_factory=list)
    last_checkpoint: Optional[str] = None
    interaction_state: dict = Field(default_factory=dict)


class ReaderProgressResponse(BaseModel):
    experience_id: str
    current_screen_id: Optional[str] = None
    completed_screen_ids: list[str] = Field(default_factory=list)
    last_checkpoint: Optional[str] = None
    interaction_state: dict = Field(default_factory=dict)
    updated_at: Optional[datetime] = None
