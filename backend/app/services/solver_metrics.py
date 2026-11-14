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

# Creating a solver session starts a browser. It is stored under its own source
# and left out of the page request statistics, which it would otherwise distort.
SESSION_SETUP_SOURCE = "fanficfare_session"


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


class SolverTimer:
    """Lets the measured code leave out time that does not belong to the request."""

    def __init__(self) -> None:
        self.excluded_seconds = 0.0
        self.discarded = False

    def exclude(self, seconds: float) -> None:
        self.excluded_seconds += max(0.0, seconds)

    def discard(self) -> None:
        """Record nothing, because the request itself was never sent."""
        self.discarded = True


@contextmanager
def timed_solver_request(target_url: str, solver_url: str, source: str) -> Iterator[SolverTimer]:
    """Measure one solver request. Any exception raised inside counts as a failure."""
    timer = SolverTimer()
    started = time.monotonic()
    error_type: str | None = None
    try:
        yield timer
    except BaseException as exc:
        error_type = type(exc).__name__
        raise
    finally:
        elapsed = time.monotonic() - started - timer.excluded_seconds
        if not timer.discarded:
            _pending.append(
                _Measurement(
                    site=site_of(target_url),
                    solver_url=solver_url,
                    source=source,
                    success=error_type is None,
                    duration_ms=max(0.0, elapsed * 1000),
                    error_type=error_type,
                    created_at=datetime.now(timezone.utc),
                )
            )


def install_fanficfare_timing() -> None:
    """Time every request FanFicFare sends to the solver.

    FanFicFare chooses its fetcher class internally and offers no hook, so the
    class's ``request`` method is wrapped once. Its cache and its deliberate
    delay between requests both sit above ``request`` and are not measured.

    With ``use_flaresolverr_session`` set, the first request also creates the
    solver session inside ``request``. That call is measured on its own, so the
    page request's time covers only the page.
    """
    from fanficfare.fetchers.fetcher_flaresolverr_proxy import FlareSolverr_ProxyFetcher

    original = FlareSolverr_ProxyFetcher.request
    if getattr(original, _TIMED_MARKER, False):
        return

    def request(self: Any, method: str, url: str, headers: Any = None, parameters: Any = None) -> Any:
        solver_url = solver_base_url(self.getConfig)
        send = self.super_request
        with timed_solver_request(url, solver_url, "fanficfare") as page_timer:

            def send_timing_session_setup(*args: Any, **kwargs: Any) -> Any:
                if (kwargs.get("json") or {}).get("cmd") != "sessions.create":
                    return send(*args, **kwargs)
                setup_started = time.monotonic()
                try:
                    with timed_solver_request(url, solver_url, SESSION_SETUP_SOURCE):
                        return send(*args, **kwargs)
                except BaseException:
                    page_timer.discard()
                    raise
                finally:
                    page_timer.exclude(time.monotonic() - setup_started)

            self.super_request = send_timing_session_setup
            try:
                return original(self, method, url, headers=headers, parameters=parameters)
            finally:
                self.super_request = send

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
    """Statistics for every site and solver pair that has been used.

    Session setup is stored but not summarised: it is not a page request.
    """
    rows = (
        await db.scalars(
            select(SolverRequestMetric)
            .where(SolverRequestMetric.source != SESSION_SETUP_SOURCE)
            .order_by(SolverRequestMetric.created_at.asc())
        )
    ).all()
    grouped: dict[tuple[str, str], list[SolverRequestMetric]] = defaultdict(list)
    for row in rows:
        grouped[(row.site, row.solver_url)].append(row)
    now = datetime.now(timezone.utc)
    return [
        SolverStats(site=site, solver_url=solver_url, **summarize_attempts(attempts, now).model_dump())
        for (site, solver_url), attempts in sorted(grouped.items())
    ]
