"""Request middleware: correlation IDs and access logging."""

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from .observability_context import request_id_var

logger = logging.getLogger("story_manager.access")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_QUIET_SUCCESS_PATHS = frozenset(
    {
        "/api/dashboard/attention",
        "/api/logs",
        "/api/observability/health",
        "/api/observability/job-metrics",
        "/api/processing/jobs",
        "/health",
        "/health/live",
        "/health/ready",
    }
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assigns a unique request ID to each incoming request and includes it in the response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        rid = supplied if _SAFE_REQUEST_ID.fullmatch(supplied) else uuid.uuid4().hex[:12]
        request.state.request_id = rid
        token = request_id_var.set(rid)
        started = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            status_code = response.status_code if response is not None else 500
            log = (
                logger.debug
                if request.method == "GET" and status_code < 400 and request.url.path in _QUIET_SUCCESS_PATHS
                else logger.info
            )
            log(
                "%s %s completed with %s in %sms",
                request.method,
                request.url.path,
                status_code,
                duration_ms,
            )
            request_id_var.reset(token)
