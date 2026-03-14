"""Reader API key helpers and authentication dependencies."""

from __future__ import annotations

import hashlib
import hmac
import secrets
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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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
