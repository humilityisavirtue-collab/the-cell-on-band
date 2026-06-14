"""chapters.py — handoff §9.2/9.3: create a chapter from text or upload."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas import ChapterResponse, ChapterTextRequest
from app.services import job_service

router = APIRouter(prefix="/chapters", tags=["chapters"])


def _to_response(chapter) -> ChapterResponse:
    return ChapterResponse(
        chapter_id=chapter.id, book_id=chapter.book_id, title=chapter.title,
        source_type=chapter.source_type, created_at=chapter.created_at)


@router.post("/text", response_model=ChapterResponse, status_code=201)
async def create_text_chapter(
        req: ChapterTextRequest,
        session: AsyncSession = Depends(get_session)) -> ChapterResponse:
    chapter = await job_service.create_chapter_from_text(session, req)
    return _to_response(chapter)


@router.post("/upload", response_model=ChapterResponse, status_code=201)
async def upload_chapter(
        file: UploadFile = File(...),
        book_title: str | None = Form(default=None),
        chapter_title: str | None = Form(default=None),
        session: AsyncSession = Depends(get_session)) -> ChapterResponse:
    content = await file.read()
    chapter = await job_service.create_chapter_from_upload(
        session, file.filename or "", content, book_title, chapter_title)
    return _to_response(chapter)
