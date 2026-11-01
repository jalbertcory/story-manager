"""Optional shared bearer-token authentication for the AI service adapters.

The model services usually run on a trusted LAN next to Story Manager, so
authentication is off unless ``AI_SERVICE_API_KEY`` is set. When it is set,
every endpoint except ``/health`` requires ``Authorization: Bearer <key>``.
"""

from __future__ import annotations

from collections.abc import Callable
import hmac
import os

from fastapi import HTTPException, Request

API_KEY_ENV = "AI_SERVICE_API_KEY"
# Container health checks and the GPU scheduler probe these without credentials.
PUBLIC_PATHS = frozenset({"/health"})


def configured_api_key(*fallback_envs: str) -> str | None:
    """Return the shared key, or the first non-empty service-specific fallback."""
    for name in (API_KEY_ENV, *fallback_envs):
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return None


def bearer_auth(*fallback_envs: str) -> Callable[[Request], None]:
    """Build an app-wide FastAPI dependency that enforces the configured key."""
    api_key = configured_api_key(*fallback_envs)
    expected = api_key.encode() if api_key is not None else None

    def require_api_key(request: Request) -> None:
        if expected is None or request.url.path in PUBLIC_PATHS:
            return
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), expected):
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing service API key.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return require_api_key
