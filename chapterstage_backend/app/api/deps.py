"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.errors import APIError, AUTH_REQUIRED
from app.models import User
from app.services import auth_service


async def get_current_user(
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise APIError(AUTH_REQUIRED, "Bearer token required.", status_code=401)
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise APIError(AUTH_REQUIRED, "Bearer token required.", status_code=401)
    return await auth_service.get_user_for_token(session, token)
