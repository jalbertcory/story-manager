"""Temporarily reject new API mutations while a consistent backup is made."""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .services.backup_barrier import BackupInProgressError, backup_barrier

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class BackupWriteBarrierMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _SAFE_METHODS or not request.url.path.startswith("/api/"):
            return await call_next(request)
        try:
            async with backup_barrier.mutation():
                return await call_next(request)
        except BackupInProgressError as exc:
            return JSONResponse(
                status_code=503,
                headers={"Retry-After": "5"},
                content={"detail": str(exc)},
            )
