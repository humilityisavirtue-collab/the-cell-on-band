"""Auth endpoints for account-backed reader progress."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_session
from app.models import User
from app.schemas import (AuthLoginRequest, AuthRegisterRequest, AuthResponse,
                         UserResponse)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])
SESSION_COOKIE = "chapterstage_session"


def _user_response(user: User) -> UserResponse:
    return UserResponse(user_id=user.id, email=user.email,
                        created_at=user.created_at)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
        req: AuthRegisterRequest,
        response: Response,
        session: AsyncSession = Depends(get_session)) -> AuthResponse:
    user = await auth_service.register_user(session, req.email, req.password)
    token = await auth_service.create_session(session, user)
    _set_session_cookie(response, token)
    return AuthResponse(access_token=token, user=_user_response(user))


@router.post("/login", response_model=AuthResponse)
async def login(
        req: AuthLoginRequest,
        response: Response,
        session: AsyncSession = Depends(get_session)) -> AuthResponse:
    user = await auth_service.authenticate_user(session, req.email, req.password)
    token = await auth_service.create_session(session, user)
    _set_session_cookie(response, token)
    return AuthResponse(access_token=token, user=_user_response(user))


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)) -> UserResponse:
    return _user_response(user)
