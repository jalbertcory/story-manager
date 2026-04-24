"""Admin authentication endpoints."""

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from ..auth import (
    ADMIN_AUTH_COOKIE,
    ADMIN_AUTH_DISABLED,
    ADMIN_SESSION_SECONDS,
    create_admin_session_token,
    get_admin_auth_mode,
    is_admin_auth_enabled,
    validate_admin_session_token,
    verify_admin_password,
)

router = APIRouter()


class AdminAuthStatus(BaseModel):
    mode: str
    authenticated: bool


class AdminLoginRequest(BaseModel):
    password: str


@router.get("/api/auth/status", response_model=AdminAuthStatus)
async def auth_status(request: Request) -> AdminAuthStatus:
    mode = get_admin_auth_mode()
    authenticated = not is_admin_auth_enabled()
    if is_admin_auth_enabled():
        authenticated = validate_admin_session_token(request.cookies.get(ADMIN_AUTH_COOKIE))
    return AdminAuthStatus(mode=mode, authenticated=authenticated)


@router.post("/api/auth/login", response_model=AdminAuthStatus)
async def login(request: AdminLoginRequest, response: Response) -> AdminAuthStatus:
    if not is_admin_auth_enabled():
        return AdminAuthStatus(mode=ADMIN_AUTH_DISABLED, authenticated=True)

    if not verify_admin_password(request.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")

    response.set_cookie(
        ADMIN_AUTH_COOKIE,
        create_admin_session_token(),
        max_age=ADMIN_SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return AdminAuthStatus(mode=get_admin_auth_mode(), authenticated=True)


@router.post("/api/auth/logout", response_model=AdminAuthStatus)
async def logout(response: Response) -> AdminAuthStatus:
    response.delete_cookie(ADMIN_AUTH_COOKIE, samesite="lax", secure=False)
    return AdminAuthStatus(mode=get_admin_auth_mode(), authenticated=not is_admin_auth_enabled())
