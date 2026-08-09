"""Correlation context shared by HTTP requests, workers, and log handlers."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
job_id_var: ContextVar[int | None] = ContextVar("job_id", default=None)


@contextmanager
def correlation_context(*, request_id: str = "", job_id: int | None = None) -> Iterator[None]:
    """Temporarily attach correlation identifiers to all logs in this context."""
    request_token = request_id_var.set(request_id)
    job_token = job_id_var.set(job_id)
    try:
        yield
    finally:
        job_id_var.reset(job_token)
        request_id_var.reset(request_token)
