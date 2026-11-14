"""Timing and outcome of requests sent to a Cloudflare solver (FlareSolverr-compatible).

Solver requests are made from worker threads, by FanFicFare and by this
application's own fetchers. A thread cannot use the event loop's database
session, so each request is measured where it happens and queued in memory.
The async caller that started the work writes the queue to the database.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import SessionLocal
from ..endpoint_types import SolverStats
from ..models import SolverRequestMetric
from .endpoint_metrics import summarize_attempts

logger = logging.getLogger(__name__)

# Bounded so a database outage cannot grow memory without limit.
_MAX_PENDING = 10_000
_TIMED_MARKER = "_story_manager_solver_timing"


@dataclass(frozen=True)
class _Measurement:
    site: str
    solver_url: str
    source: str
    success: bool
    duration_ms: float
    error_type: str | None
    created_at: datetime


_pending: deque[_Measurement] = deque(maxlen=_MAX_PENDING)


def solver_base_url(get_config: Callable[[str, str], str]) -> str:
    """protocol://host:port of the solver configured in FanFicFare's settings."""
    return (
        f"{get_config('flaresolverr_proxy_protocol', 'http')}://"
        f"{get_config('flaresolverr_proxy_address', 'localhost')}:"
        f"{get_config('flaresolverr_proxy_port', '8191')}"
    )


def site_of(url: str) -> str:
    """Hostname without a leading www, so both spellings of a site share one row."""
    host = (urlsplit(url).hostname or "unknown").lower()
    return host.removeprefix("www.")


def reset_pending() -> None:
    _pending.clear()


def pending_count() -> int:
    return len(_pending)


@contextmanager
def timed_solver_request(target_url: str, solver_url: str, source: str) -> Iterator[None]:
    """Measure one solver request. Any exception raised inside counts as a failure."""
    started = time.monotonic()
    error_type: str | None = None
    try:
        yield
    except BaseException as exc:
        error_type = type(exc).__name__
        raise
    finally:
        _pending.append(
            _Measurement(
                site=site_of(target_url),
                solver_url=solver_url,
                source=source,
                success=error_type is None,
                duration_ms=max(0.0, (time.monotonic() - started) * 1000),
                error_type=error_type,
                created_at=datetime.now(timezone.utc),
            )
        )


def install_fanficfare_timing() -> None:
    """Time every request FanFicFare sends to the solver.

    FanFicFare chooses its fetcher class internally and offers no hook, so the
    class's ``request`` method is wrapped once. Its cache and its deliberate
    delay between requests both sit above ``request`` and are not measured.
    """
    from fanficfare.fetchers.fetcher_flaresolverr_proxy import FlareSolverr_ProxyFetcher

    original = FlareSolverr_ProxyFetcher.request
    if getattr(original, _TIMED_MARKER, False):
        return

    def request(self: Any, method: str, url: str, headers: Any = None, parameters: Any = None) -> Any:
        with timed_solver_request(url, solver_base_url(self.getConfig), "fanficfare"):
            return original(self, method, url, headers=headers, parameters=parameters)

    setattr(request, _TIMED_MARKER, True)
    FlareSolverr_ProxyFetcher.request = request


async def flush_solver_metrics() -> None:
    """Write queued measurements. Statistics must never fail the work they describe."""
    batch: list[_Measurement] = []
    while True:
        try:
            batch.append(_pending.popleft())
        except IndexError:
            break
    if not batch:
        return
    try:
        async with SessionLocal() as db:
            db.add_all(
                SolverRequestMetric(
                    site=item.site,
                    solver_url=item.solver_url,
                    source=item.source,
                    success=item.success,
                    duration_ms=item.duration_ms,
                    error_type=item.error_type,
                    created_at=item.created_at,
                )
                for item in batch
            )
            await db.commit()
    except Exception:
        logger.warning("Could not save %s solver request measurements.", len(batch), exc_info=True)


async def solver_summaries(db: AsyncSession) -> list[SolverStats]:
    """Statistics for every site and solver pair that has been used."""
    rows = (await db.scalars(select(SolverRequestMetric).order_by(SolverRequestMetric.created_at.asc()))).all()
    grouped: dict[tuple[str, str], list[SolverRequestMetric]] = defaultdict(list)
    for row in rows:
        grouped[(row.site, row.solver_url)].append(row)
    now = datetime.now(timezone.utc)
    return [
        SolverStats(site=site, solver_url=solver_url, **summarize_attempts(attempts, now).model_dump())
        for (site, solver_url), attempts in sorted(grouped.items())
    ]
