"""document_parser.py — input -> validated chapter text (handoff §9.2/9.3, §10).

M1: text and .txt uploads fully supported. .pdf uses pypdf if present, else fails
HONESTLY with EXTRACTION_FAILED (no fake success) — real PDF extraction + scanned/
encrypted rejection is a later milestone. Length + type + size limits raise the
exact §10 error codes the frontend switches on.
"""
from __future__ import annotations

from app.config import settings
from app.errors import (APIError, CHAPTER_TOO_LONG, CHAPTER_TOO_SHORT,
                        EXTRACTION_FAILED, FILE_TOO_LARGE, INVALID_FILE_TYPE)


def validate_chapter_text(text: str) -> str:
    """Enforce handoff §9.2: 500..80000 chars. Raises §10 codes on violation."""
    n = len(text or "")
    if n < settings.MIN_CHAPTER_CHARS:
        raise APIError(CHAPTER_TOO_SHORT,
                       "Chapter text must be at least %d characters (got %d)."
                       % (settings.MIN_CHAPTER_CHARS, n),
                       {"min": settings.MIN_CHAPTER_CHARS, "got": n})
    if n > settings.MAX_CHAPTER_CHARS:
        raise APIError(CHAPTER_TOO_LONG,
                       "Chapter text exceeds %d characters (got %d)."
                       % (settings.MAX_CHAPTER_CHARS, n),
                       {"max": settings.MAX_CHAPTER_CHARS, "got": n})
    return text


def parse_upload(filename: str, content: bytes) -> tuple[str, str]:
    """Validate an upload and extract text. Returns (source_type, text).
    Raises §10 codes for wrong type / too large / extraction failure."""
    name = (filename or "").lower()
    if not name.endswith(settings.ALLOWED_UPLOAD_EXT):
        raise APIError(INVALID_FILE_TYPE,
                       "Only %s uploads are accepted."
                       % ", ".join(settings.ALLOWED_UPLOAD_EXT),
                       {"filename": filename})
    if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise APIError(FILE_TOO_LARGE,
                       "File exceeds %d MB." % settings.MAX_UPLOAD_MB,
                       {"max_mb": settings.MAX_UPLOAD_MB, "bytes": len(content)})

    if name.endswith(".txt"):
        text = content.decode("utf-8", errors="replace")
        return "text", validate_chapter_text(text)

    # .pdf — real extraction via pypdf if available; otherwise honest failure.
    try:
        import io
        from pypdf import PdfReader  # type: ignore
    except Exception:
        raise APIError(EXTRACTION_FAILED,
                       "PDF text extraction is not available in this build "
                       "(install pypdf). Use /chapters/text or a .txt upload.",
                       {"reason": "pypdf_missing"})
    try:
        reader = PdfReader(io.BytesIO(content))
        if getattr(reader, "is_encrypted", False):
            raise APIError(EXTRACTION_FAILED, "Encrypted PDFs are not supported.",
                           {"reason": "encrypted"})
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except APIError:
        raise
    except Exception as e:
        raise APIError(EXTRACTION_FAILED, "Could not read the PDF.",
                       {"reason": type(e).__name__})
    if not text.strip():
        # no extractable text == scanned PDF (no OCR in MVP)
        raise APIError(EXTRACTION_FAILED,
                       "No extractable text (scanned PDF? no OCR in MVP).",
                       {"reason": "no_text"})
    return "pdf", validate_chapter_text(text)
