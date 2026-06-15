"""Account and bearer-session helpers."""
from __future__ import annotations

import hashlib
import secrets

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import (APIError, EMAIL_ALREADY_REGISTERED, INVALID_CREDENTIALS)
from app.models import User, UserSession, _now

_pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def register_user(session: AsyncSession, email: str, password: str) -> User:
    clean = _normalize_email(email)
    if not clean or "@" not in clean:
        raise APIError("INVALID_REQUEST", "A valid email address is required.")
    existing = (await session.execute(
        select(User).where(User.email == clean))).scalar_one_or_none()
    if existing is not None:
        raise APIError(EMAIL_ALREADY_REGISTERED, "Email is already registered.")
    user = User(email=clean, password_hash=_pwd_context.hash(password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate_user(
        session: AsyncSession, email: str, password: str) -> User:
    clean = _normalize_email(email)
    user = (await session.execute(
        select(User).where(User.email == clean))).scalar_one_or_none()
    if user is None or not _pwd_context.verify(password, user.password_hash):
        raise APIError(INVALID_CREDENTIALS, "Invalid email or password.")
    return user


async def create_session(session: AsyncSession, user: User) -> str:
    token = secrets.token_urlsafe(32)
    row = UserSession(user_id=user.id, token_hash=_hash_token(token))
    session.add(row)
    await session.commit()
    return token


async def get_user_for_token(session: AsyncSession, token: str) -> User:
    token_hash = _hash_token(token)
    row = (await session.execute(
        select(UserSession).where(
            UserSession.token_hash == token_hash))).scalar_one_or_none()
    if row is None:
        raise APIError(INVALID_CREDENTIALS, "Invalid or expired token.",
                       status_code=401)
    user = await session.get(User, row.user_id)
    if user is None:
        raise APIError(INVALID_CREDENTIALS, "Invalid or expired token.",
                       status_code=401)
    row.last_seen_at = _now()
    session.add(row)
    await session.commit()
    return user
