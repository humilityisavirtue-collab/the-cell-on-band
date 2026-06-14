"""job_service.py — chapter + generation-job persistence (handoff §9.2-9.5, §4.2).

M1 is the lifecycle's front door: create a chapter (book auto-created), open a job
row at status `queued`, fetch its status. The workflow that advances the status
(M3/M4 ChapterWorkflow) wires in at M4-live; here the row just exists and is
fetchable, which is what the frontend polls.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import APIError, INVALID_REQUEST, JOB_NOT_FOUND
from app.models import Book, Chapter, GenerationJob
from app.schemas import ChapterTextRequest, JobCreateRequest


async def create_chapter_from_text(
        session: AsyncSession, req: ChapterTextRequest) -> Chapter:
    from app.services.document_parser import validate_chapter_text
    text = validate_chapter_text(req.text)
    title = req.chapter_title or req.book_title or "Untitled Chapter"
    book = Book(title=req.book_title or "Untitled")
    session.add(book)
    await session.flush()                       # get book.id
    chapter = Chapter(book_id=book.id, title=title,
                      source_type="text", source_text=text)
    session.add(chapter)
    await session.commit()
    await session.refresh(chapter)
    return chapter


async def create_chapter_from_upload(
        session: AsyncSession, filename: str, content: bytes,
        book_title: str | None, chapter_title: str | None) -> Chapter:
    from app.services.document_parser import parse_upload
    source_type, text = parse_upload(filename, content)
    title = chapter_title or book_title or filename or "Untitled Chapter"
    book = Book(title=book_title or "Untitled")
    session.add(book)
    await session.flush()
    chapter = Chapter(book_id=book.id, title=title,
                      source_type=source_type, source_text=text)
    session.add(chapter)
    await session.commit()
    await session.refresh(chapter)
    return chapter


async def create_job(session: AsyncSession, req: JobCreateRequest) -> GenerationJob:
    chapter = await session.get(Chapter, req.chapter_id)
    if chapter is None:
        raise APIError(INVALID_REQUEST, "Unknown chapter_id.",
                       {"chapter_id": req.chapter_id})
    job = GenerationJob(
        chapter_id=req.chapter_id, status="queued",
        audience_level=req.audience_level, experience_style=req.experience_style,
        target_screen_count=req.target_screen_count,
        enable_auto_brainstorm=req.enable_auto_brainstorm)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def get_job(session: AsyncSession, job_id: str) -> GenerationJob:
    job = await session.get(GenerationJob, job_id)
    if job is None:
        raise APIError(JOB_NOT_FOUND, "No such job.", {"job_id": job_id})
    return job


async def count_jobs(session: AsyncSession) -> int:
    return (await session.execute(select(func.count(GenerationJob.id)))).scalar_one()
