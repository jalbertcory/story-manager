"""Middleware that protects admin API routes when password auth is enabled."""

from contextlib import aclosing

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth import ADMIN_AUTH_COOKIE, is_admin_auth_enabled, is_admin_session_valid
from .database import get_db


class AdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._requires_admin_auth(request):
            return await call_next(request)

        try:
            authenticated = await self._session_is_valid(request)
        except RuntimeError as exc:
            return JSONResponse(status_code=500, content={"detail": str(exc)})

        if not authenticated:
            return JSONResponse(status_code=401, content={"detail": "Admin authentication required"})

        return await call_next(request)

    @staticmethod
    async def _session_is_valid(request: Request) -> bool:
        token = request.cookies.get(ADMIN_AUTH_COOKIE)
        if not token:
            return False
        # Resolve the session through the app's get_db dependency so overrides
        # (tests, alternate engines) see the same database as the routes.
        session_factory = request.app.dependency_overrides.get(get_db, get_db)
        async with aclosing(session_factory()) as sessions:
            async for db in sessions:
                return await is_admin_session_valid(db, token)
        return False

    @staticmethod
    def _requires_admin_auth(request: Request) -> bool:
        if not is_admin_auth_enabled():
            return False
        path = request.url.path
        protected_api = path.startswith("/api/") and not path.startswith("/api/auth/")
        protected_audiobook = path == "/library/audiobooks" or path.startswith("/library/audiobooks/")
        return protected_api or protected_audiobook
