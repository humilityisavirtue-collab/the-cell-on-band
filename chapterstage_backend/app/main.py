"""main.py — FastAPI app: routers, §10 error handlers, DB init, static mount.

Mounts the §9 API under /api/v1 and serves generated experiences from
GENERATED_SITE_ROOT at /public/experiences (handoff §11 isolated static dir;
populated at M5). Pydantic validation failures are reshaped into the §10
{error:{code,message,details}} envelope so the frontend sees ONE error shape.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import auth, chapters, experiences, health, jobs
from app.config import settings
from app.errors import APIError, INTERNAL_ERROR, INVALID_REQUEST, api_error_handler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.database import init_db
    await init_db()
    yield


app = FastAPI(title="ChapterStage Backend", version=settings.VERSION,
              lifespan=lifespan)

app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(chapters.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(experiences.router, prefix="/api/v1")


@app.exception_handler(APIError)
async def _api_error(request: Request, exc: APIError) -> JSONResponse:
    return await api_error_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request,
                            exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"code": INVALID_REQUEST,
                           "message": "Request validation failed.",
                           "details": {"errors": exc.errors()}}})


@app.exception_handler(Exception)
async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": {"code": INTERNAL_ERROR, "message": str(exc),
                           "details": {}}})


# § 11 isolated static dir for generated experiences (M5 populates it)
_site_root = settings.GENERATED_SITE_ROOT
os.makedirs(_site_root, exist_ok=True)
app.mount("/public/experiences",
          StaticFiles(directory=_site_root, html=True), name="experiences")


@app.middleware("http")
async def _csp_on_public(request: Request, call_next):
    """THE security boundary for served experiences (§11): a strict default-deny
    CSP header the browser enforces, so an obfuscated fetch/eval that slips past
    the static validator's denylist STILL cannot reach the network or run injected
    code. The page cannot weaken a server-sent CSP. Allowlist > denylist."""
    from app.services.site_validator import STRICT_CSP_HEADER
    response = await call_next(request)
    if request.url.path.startswith("/public/experiences"):
        response.headers["Content-Security-Policy"] = STRICT_CSP_HEADER
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
    return response
