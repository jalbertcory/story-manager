"""Middleware that protects admin API routes when password auth is enabled."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth import ADMIN_AUTH_COOKIE, is_admin_auth_enabled, validate_admin_session_token


class AdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not self._requires_admin_auth(request):
            return await call_next(request)

        try:
            authenticated = validate_admin_session_token(request.cookies.get(ADMIN_AUTH_COOKIE))
        except RuntimeError as exc:
            return JSONResponse(status_code=500, content={"detail": str(exc)})

        if not authenticated:
            return JSONResponse(status_code=401, content={"detail": "Admin authentication required"})

        return await call_next(request)

    @staticmethod
    def _requires_admin_auth(request: Request) -> bool:
        if not is_admin_auth_enabled():
            return False
        path = request.url.path
        protected_api = path.startswith("/api/") and not path.startswith("/api/auth/")
        protected_audiobook = path == "/library/audiobooks" or path.startswith("/library/audiobooks/")
        return protected_api or protected_audiobook
