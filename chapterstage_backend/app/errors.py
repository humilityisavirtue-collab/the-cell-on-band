"""errors.py — the handoff §10 error model: {error:{code, message, details}}.

One APIError exception carries an HTTP status + a stable error code from §10. The
handler renders the exact §10 envelope so the frontend can switch on `error.code`.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

# § 10 codes — the stable set the frontend switches on
INVALID_REQUEST = "INVALID_REQUEST"
INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
FILE_TOO_LARGE = "FILE_TOO_LARGE"
EXTRACTION_FAILED = "EXTRACTION_FAILED"
CHAPTER_TOO_SHORT = "CHAPTER_TOO_SHORT"
CHAPTER_TOO_LONG = "CHAPTER_TOO_LONG"
JOB_NOT_FOUND = "JOB_NOT_FOUND"
JOB_ALREADY_RUNNING = "JOB_ALREADY_RUNNING"
BAND_ROOM_CREATE_FAILED = "BAND_ROOM_CREATE_FAILED"
AGENT_WORKFLOW_FAILED = "AGENT_WORKFLOW_FAILED"
SITE_VALIDATION_FAILED = "SITE_VALIDATION_FAILED"
PUBLISH_FAILED = "PUBLISH_FAILED"
INTERNAL_ERROR = "INTERNAL_ERROR"
AUTH_REQUIRED = "AUTH_REQUIRED"
INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
EMAIL_ALREADY_REGISTERED = "EMAIL_ALREADY_REGISTERED"

_STATUS = {
    INVALID_REQUEST: 400,
    INVALID_FILE_TYPE: 415,
    FILE_TOO_LARGE: 413,
    CHAPTER_TOO_SHORT: 422,
    CHAPTER_TOO_LONG: 422,
    EXTRACTION_FAILED: 422,
    JOB_NOT_FOUND: 404,
    JOB_ALREADY_RUNNING: 409,
    AUTH_REQUIRED: 401,
    INVALID_CREDENTIALS: 401,
    EMAIL_ALREADY_REGISTERED: 409,
}


class APIError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None,
                 status_code: int | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code or _STATUS.get(code, 500)
        super().__init__(message)

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content={"error": {"code": self.code, "message": self.message,
                               "details": self.details}})


async def api_error_handler(_request: Request, exc: APIError) -> JSONResponse:
    return exc.to_response()
