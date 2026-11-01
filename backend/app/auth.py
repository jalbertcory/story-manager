"""Reader API key helpers and admin authentication dependencies."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasic, HTTPBasicCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import models
from .database import get_db

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)
_basic = HTTPBasic(auto_error=False)

ADMIN_AUTH_COOKIE = "story_manager_admin"
ADMIN_AUTH_DISABLED = "disabled"
ADMIN_AUTH_PASSWORD = "password"
ADMIN_SESSION_SECONDS = 60 * 60 * 24 * 14
ADMIN_AUTH_MODES = {ADMIN_AUTH_DISABLED, ADMIN_AUTH_PASSWORD}
ADMIN_COOKIE_SECURE_AUTO = "auto"
ADMIN_AUTH_STATE_ID = 1


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


LAST_USED_UPDATE_INTERVAL = timedelta(minutes=5)


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


def warn_if_admin_auth_disabled() -> None:
    """Make an unauthenticated deployment obvious in the startup log."""
    if is_admin_auth_enabled():
        return
    logger.warning(
        "!!! Story Manager admin authentication is DISABLED (STORY_MANAGER_AUTH_MODE=disabled). "
        "Every admin API and audiobook file is open to anyone who can reach this server. "
        "Only run this way behind an authenticating reverse proxy (for example Authentik or "
        "Authelia forward auth); otherwise set STORY_MANAGER_ADMIN_PASSWORD. !!!"
    )


def _admin_password() -> Optional[str]:
    password = os.getenv("STORY_MANAGER_ADMIN_PASSWORD")
    return password if password else None


def _admin_session_secret() -> Optional[str]:
    return os.getenv("STORY_MANAGER_ADMIN_SESSION_SECRET") or _admin_password()


def verify_admin_password(password: str) -> bool:
    expected = _admin_password()
    if expected is None:
        return False
    # compare_digest only accepts ASCII str, so compare UTF-8 bytes to keep
    # non-ASCII passwords from raising instead of failing the comparison.
    return hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))


def _admin_signing_key() -> bytes:
    secret = _admin_session_secret()
    if secret is None:
        raise RuntimeError("Admin auth is enabled but no admin password/session secret is configured")
    # Bind sessions to the current password as well as the secret, so changing
    # the password revokes existing sessions even with a dedicated session secret.
    password = (_admin_password() or "").encode("utf-8")
    return hmac.new(secret.encode("utf-8"), b"story-manager-admin-session\0" + password, hashlib.sha256).digest()


def _sign_admin_payload(payload: str) -> str:
    return hmac.new(_admin_signing_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_admin_session_token(now: int | None = None, epoch: int = 0) -> str:
    expires_at = (now or int(time.time())) + ADMIN_SESSION_SECONDS
    payload = base64.urlsafe_b64encode(f"{expires_at}:{epoch}".encode("ascii")).decode("ascii").rstrip("=")
    signature = _sign_admin_payload(payload)
    return f"{payload}.{signature}"


def validate_admin_session_token(token: str | None, now: int | None = None, epoch: int = 0) -> bool:
    """Check signature, expiry, and that the token was issued in the current session epoch."""
    if not token or "." not in token:
        return False

    payload, signature = token.split(".", 1)
    expected_signature = _sign_admin_payload(payload)
    if not hmac.compare_digest(signature.encode("utf-8"), expected_signature.encode("utf-8")):
        return False

    try:
        padded = payload + "=" * (-len(payload) % 4)
        expires_text, epoch_text = base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii").split(":", 1)
        expires_at = int(expires_text)
        token_epoch = int(epoch_text)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False

    return token_epoch == epoch and expires_at > (now or int(time.time()))


async def get_admin_session_epoch(db: AsyncSession) -> int:
    result = await db.execute(
        select(models.AdminAuthState.session_epoch).where(models.AdminAuthState.id == ADMIN_AUTH_STATE_ID)
    )
    epoch = result.scalar_one_or_none()
    return epoch if epoch is not None else 0


async def revoke_admin_sessions(db: AsyncSession) -> int:
    """Advance the session epoch, invalidating every previously issued admin cookie."""
    result = await db.execute(
        update(models.AdminAuthState)
        .where(models.AdminAuthState.id == ADMIN_AUTH_STATE_ID)
        .values(session_epoch=models.AdminAuthState.session_epoch + 1)
        .returning(models.AdminAuthState.session_epoch)
    )
    epoch = result.scalar_one_or_none()
    if epoch is None:
        epoch = 1
        db.add(models.AdminAuthState(id=ADMIN_AUTH_STATE_ID, session_epoch=epoch))
    await db.commit()
    return epoch


async def is_admin_session_valid(db: AsyncSession, token: str | None) -> bool:
    if not token:
        return False
    return validate_admin_session_token(token, epoch=await get_admin_session_epoch(db))


@dataclass
class _LoginFailures:
    count: int
    last_failure: float
    locked_until: float
    next_locked_check: float = 0.0


class LoginThrottle:
    """Per-client exponential backoff for failed admin logins.

    The first ``free_attempts`` failures are not delayed; each later failure
    doubles the lockout up to ``max_lockout_seconds``. A successful login, or
    ``reset_after_seconds`` without failures, clears the client's history.

    A locked-out client is not refused outright: its password is still checked,
    at most once per ``locked_check_interval_seconds``, and a correct one signs
    in. Behind a reverse proxy whose forwarded headers are not trusted every
    visitor shares the proxy's address, so a hard lockout would let anyone lock
    the admin out with a few bad guesses.
    """

    def __init__(
        self,
        *,
        free_attempts: int = 5,
        base_lockout_seconds: float = 1.0,
        max_lockout_seconds: float = 15 * 60,
        locked_check_interval_seconds: float = 1.0,
        reset_after_seconds: float = 60 * 60,
        max_tracked_clients: int = 10_000,
    ) -> None:
        self.free_attempts = free_attempts
        self.base_lockout_seconds = base_lockout_seconds
        self.max_lockout_seconds = max_lockout_seconds
        self.locked_check_interval_seconds = locked_check_interval_seconds
        self.reset_after_seconds = reset_after_seconds
        self.max_tracked_clients = max_tracked_clients
        self._failures: dict[str, _LoginFailures] = {}
        self._lock = threading.Lock()

    def retry_after(self, client: str, now: float | None = None) -> int:
        """Seconds the client must wait before another attempt (0 when allowed)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            entry = self._current(client, now)
            if entry is None or entry.locked_until <= now:
                return 0
            return max(1, int(entry.locked_until - now + 0.999))

    def admit_check(self, client: str, now: float | None = None) -> int:
        """Claim a password check for the client: 0 when allowed, else seconds to wait.

        Unlocked clients are always admitted; a locked-out client gets one check
        per ``locked_check_interval_seconds``.
        """
        now = time.monotonic() if now is None else now
        with self._lock:
            entry = self._current(client, now)
            if entry is None or entry.locked_until <= now:
                return 0
            if entry.next_locked_check > now:
                return max(1, int(entry.next_locked_check - now + 0.999))
            entry.next_locked_check = now + self.locked_check_interval_seconds
            return 0

    def record_failure(self, client: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            entry = self._current(client, now)
            if entry is None:
                if len(self._failures) >= self.max_tracked_clients:
                    self._prune(now)
                entry = _LoginFailures(count=0, last_failure=now, locked_until=0.0)
                self._failures[client] = entry
            entry.count += 1
            entry.last_failure = now
            excess = entry.count - self.free_attempts
            if excess > 0:
                lockout = min(self.base_lockout_seconds * 2 ** (excess - 1), self.max_lockout_seconds)
                entry.locked_until = now + lockout

    def record_success(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()

    def _current(self, client: str, now: float) -> _LoginFailures | None:
        entry = self._failures.get(client)
        if entry is not None and entry.locked_until <= now and now - entry.last_failure >= self.reset_after_seconds:
            del self._failures[client]
            return None
        return entry

    def _prune(self, now: float) -> None:
        stale = [
            client
            for client, entry in self._failures.items()
            if entry.locked_until <= now and now - entry.last_failure >= self.reset_after_seconds
        ]
        for client in stale:
            del self._failures[client]
        if len(self._failures) >= self.max_tracked_clients:
            oldest = min(self._failures, key=lambda client: self._failures[client].last_failure)
            del self._failures[oldest]


admin_login_throttle = LoginThrottle()


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

    # Audio players and OPDS clients make many requests per minute; record usage
    # at a coarse granularity instead of committing a write on every request.
    now = _now_utc()
    last_used = api_key.last_used_at
    if last_used is not None and last_used.tzinfo is None:
        last_used = last_used.replace(tzinfo=timezone.utc)
    if last_used is None or now - last_used >= LAST_USED_UPDATE_INTERVAL:
        api_key.last_used_at = now
        await db.commit()
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
