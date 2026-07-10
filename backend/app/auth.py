"""Reader API key helpers and admin authentication dependencies."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasic, HTTPBasicCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import models
from .database import get_db

_bearer = HTTPBearer(auto_error=False)
_basic = HTTPBasic(auto_error=False)

ADMIN_AUTH_COOKIE = "story_manager_admin"
ADMIN_AUTH_DISABLED = "disabled"
ADMIN_AUTH_PASSWORD = "password"
ADMIN_SESSION_SECONDS = 60 * 60 * 24 * 14
ADMIN_AUTH_MODES = {ADMIN_AUTH_DISABLED, ADMIN_AUTH_PASSWORD}
ADMIN_COOKIE_SECURE_AUTO = "auto"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_admin_auth_mode() -> str:
    configured_mode = os.getenv("STORY_MANAGER_AUTH_MODE", "").strip().lower()
    mode = configured_mode or (ADMIN_AUTH_PASSWORD if os.getenv("STORY_MANAGER_ADMIN_PASSWORD") else ADMIN_AUTH_DISABLED)
    if mode not in ADMIN_AUTH_MODES:
        allowed = ", ".join(sorted(ADMIN_AUTH_MODES))
        raise RuntimeError(f"Invalid STORY_MANAGER_AUTH_MODE={mode!r}; expected one of: {allowed}")
    if mode == ADMIN_AUTH_PASSWORD and not _admin_password():
        raise RuntimeError("STORY_MANAGER_AUTH_MODE=password requires STORY_MANAGER_ADMIN_PASSWORD")
    return mode


def is_admin_auth_enabled() -> bool:
    return get_admin_auth_mode() == ADMIN_AUTH_PASSWORD


def is_admin_cookie_secure(request: Request) -> bool:
    configured = os.getenv("STORY_MANAGER_ADMIN_COOKIE_SECURE", ADMIN_COOKIE_SECURE_AUTO).strip().lower()
    if configured == ADMIN_COOKIE_SECURE_AUTO:
        return request.scope.get("scheme") == "https"
    if configured in {"1", "true", "yes", "on"}:
        return True
    if configured in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError("Invalid STORY_MANAGER_ADMIN_COOKIE_SECURE value; expected auto, true, or false")


def validate_admin_auth_configuration() -> None:
    """Fail startup when authentication or cookie settings are invalid."""
    get_admin_auth_mode()
    configured = os.getenv("STORY_MANAGER_ADMIN_COOKIE_SECURE", ADMIN_COOKIE_SECURE_AUTO).strip().lower()
    if configured not in {ADMIN_COOKIE_SECURE_AUTO, "1", "true", "yes", "on", "0", "false", "no", "off"}:
        raise RuntimeError("Invalid STORY_MANAGER_ADMIN_COOKIE_SECURE value; expected auto, true, or false")


def _admin_password() -> Optional[str]:
    password = os.getenv("STORY_MANAGER_ADMIN_PASSWORD")
    return password if password else None


def _admin_session_secret() -> Optional[str]:
    return os.getenv("STORY_MANAGER_ADMIN_SESSION_SECRET") or _admin_password()


def verify_admin_password(password: str) -> bool:
    expected = _admin_password()
    if expected is None:
        return False
    return hmac.compare_digest(password, expected)


def _sign_admin_payload(payload: str) -> str:
    secret = _admin_session_secret()
    if secret is None:
        raise RuntimeError("Admin auth is enabled but no admin password/session secret is configured")
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_admin_session_token(now: int | None = None) -> str:
    expires_at = (now or int(time.time())) + ADMIN_SESSION_SECONDS
    payload = base64.urlsafe_b64encode(str(expires_at).encode("ascii")).decode("ascii").rstrip("=")
    signature = _sign_admin_payload(payload)
    return f"{payload}.{signature}"


def validate_admin_session_token(token: str | None, now: int | None = None) -> bool:
    if not token or "." not in token:
        return False

    payload, signature = token.split(".", 1)
    expected_signature = _sign_admin_payload(payload)
    if not hmac.compare_digest(signature, expected_signature):
        return False

    try:
        padded = payload + "=" * (-len(payload) % 4)
        expires_at = int(base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False

    return expires_at > (now or int(time.time()))


def generate_reader_token() -> tuple[str, str]:
    prefix = f"smr_{secrets.token_hex(4)}"
    secret = secrets.token_urlsafe(24)
    token = f"{prefix}_{secret}"
    return token, prefix


def _extract_prefix(token: str) -> Optional[str]:
    parts = token.split("_", 2)
    if len(parts) < 3 or parts[0] != "smr":
        return None
    return f"{parts[0]}_{parts[1]}"


async def _get_key_by_token(db: AsyncSession, token: str) -> Optional[models.ApiKey]:
    prefix = _extract_prefix(token)
    if prefix is None:
        return None

    result = await db.execute(
        select(models.ApiKey).where(
            models.ApiKey.token_prefix == prefix,
            models.ApiKey.revoked_at.is_(None),
        )
    )
    api_key = result.scalars().first()
    if api_key is None:
        return None

    if not hmac.compare_digest(api_key.token_hash, hash_token(token)):
        return None

    api_key.last_used_at = _now_utc()
    await db.commit()
    await db.refresh(api_key)
    return api_key


async def get_reader_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
    bearer: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    basic: Optional[HTTPBasicCredentials] = Depends(_basic),
    api_key_query: Optional[str] = Query(default=None, alias="api_key"),
) -> models.ApiKey:
    token = api_key_query
    if token is None and bearer is not None:
        token = bearer.credentials
    if token is None and basic is not None:
        token = basic.password

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Reader API key required",
            headers={"WWW-Authenticate": 'Basic realm="Story Manager Reader", Bearer'},
        )

    api_key = await _get_key_by_token(db, token)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid reader API key",
            headers={"WWW-Authenticate": 'Basic realm="Story Manager Reader", Bearer'},
        )

    request.state.reader_api_key_id = api_key.id
    return api_key
