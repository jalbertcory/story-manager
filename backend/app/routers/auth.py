"""Admin authentication endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..api_model import APIModel as BaseModel

from ..auth import (
    ADMIN_AUTH_COOKIE,
    ADMIN_AUTH_DISABLED,
    ADMIN_SESSION_SECONDS,
    admin_login_throttle,
    create_admin_session_token,
    get_admin_auth_mode,
    get_admin_session_epoch,
    is_admin_cookie_secure,
    is_admin_auth_enabled,
    is_admin_session_valid,
    revoke_admin_sessions,
    verify_admin_password,
)
from ..database import get_db

router = APIRouter()


class AdminAuthStatus(BaseModel):
    mode: str
    authenticated: bool


class AdminLoginRequest(BaseModel):
    password: str


def _login_client_key(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _too_many_attempts(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many failed login attempts; try again later",
        headers={"Retry-After": str(max(1, retry_after))},
    )


@router.get("/api/auth/status", response_model=AdminAuthStatus)
async def auth_status(request: Request, db: AsyncSession = Depends(get_db)) -> AdminAuthStatus:
    mode = get_admin_auth_mode()
    authenticated = not is_admin_auth_enabled()
    if is_admin_auth_enabled():
        authenticated = await is_admin_session_valid(db, request.cookies.get(ADMIN_AUTH_COOKIE))
    return AdminAuthStatus(mode=mode, authenticated=authenticated)


@router.post(
    "/api/auth/login",
    response_model=AdminAuthStatus,
    responses={429: {"description": "Too many failed login attempts from this client"}},
)
async def login(
    payload: AdminLoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> AdminAuthStatus:
    if not is_admin_auth_enabled():
        return AdminAuthStatus(mode=ADMIN_AUTH_DISABLED, authenticated=True)

    client = _login_client_key(request)
    wait = admin_login_throttle.admit_check(client)
    if wait:
        raise _too_many_attempts(wait)

    # A locked-out client is still checked so a correct password signs in even
    # when other visitors share its address (see LoginThrottle).
    was_locked = admin_login_throttle.retry_after(client) > 0
    if not verify_admin_password(payload.password):
        admin_login_throttle.record_failure(client)
        if was_locked:
            raise _too_many_attempts(admin_login_throttle.retry_after(client))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")

    admin_login_throttle.record_success(client)
    response.set_cookie(
        ADMIN_AUTH_COOKIE,
        create_admin_session_token(epoch=await get_admin_session_epoch(db)),
        max_age=ADMIN_SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=is_admin_cookie_secure(request),
    )
    return AdminAuthStatus(mode=get_admin_auth_mode(), authenticated=True)


@router.post("/api/auth/logout", response_model=AdminAuthStatus)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> AdminAuthStatus:
    # Only a currently valid session may revoke sessions; otherwise anyone could
    # sign the admin out by posting here.
    if is_admin_auth_enabled() and await is_admin_session_valid(db, request.cookies.get(ADMIN_AUTH_COOKIE)):
        await revoke_admin_sessions(db)
    response.delete_cookie(ADMIN_AUTH_COOKIE, samesite="lax", secure=is_admin_cookie_secure(request))
    return AdminAuthStatus(mode=get_admin_auth_mode(), authenticated=not is_admin_auth_enabled())
