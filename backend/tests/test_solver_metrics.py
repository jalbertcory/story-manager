from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import requests
from sqlalchemy import select

from backend.app import models
from backend.app.services import cover_images, royalroad_anubis, solver_metrics, web_novel

TRAWL = "http://192.168.1.151:8193"
FLARESOLVERR = "http://192.168.1.151:8191"


def _solver_reply(body: dict) -> MagicMock:
    reply = MagicMock()
    reply.json.return_value = body
    reply.raise_for_status.return_value = None
    return reply


async def _saved(sqlite_sessionmaker) -> list[models.SolverRequestMetric]:
    await solver_metrics.flush_solver_metrics()
    async with sqlite_sessionmaker() as db:
        return list((await db.scalars(select(models.SolverRequestMetric).order_by(models.SolverRequestMetric.id))).all())


@pytest.mark.asyncio
async def test_timed_request_records_site_solver_outcome_and_duration(monkeypatch, sqlite_sessionmaker):
    monkeypatch.setattr(solver_metrics, "SessionLocal", sqlite_sessionmaker)
    clock = iter([10.0, 10.5, 20.0, 32.6])
    # The event loop reads the same clock, so replace it only around the measured code.
    with monkeypatch.context() as patched:
        patched.setattr(solver_metrics.time, "monotonic", lambda: next(clock))
        with solver_metrics.timed_solver_request("https://www.royalroad.com/fiction/1", TRAWL, "royalroad"):
            pass
        with pytest.raises(ValueError):
            with solver_metrics.timed_solver_request("https://www.scribblehub.com/series/2/", TRAWL, "fanficfare"):
                raise ValueError("challenge not solved")

    ok, failed = await _saved(sqlite_sessionmaker)
    assert (ok.site, ok.solver_url, ok.source, ok.success, ok.error_type) == (
        "royalroad.com",
        TRAWL,
        "royalroad",
        True,
        None,
    )
    assert ok.duration_ms == pytest.approx(500)
    assert (failed.site, failed.success, failed.error_type) == ("scribblehub.com", False, "ValueError")
    assert failed.duration_ms == pytest.approx(12_600)
    assert solver_metrics.pending_count() == 0


@pytest.mark.asyncio
async def test_flush_failure_is_logged_and_never_raised(caplog):
    with solver_metrics.timed_solver_request("https://www.royalroad.com/fiction/1", TRAWL, "royalroad"):
        pass

    await solver_metrics.flush_solver_metrics()

    assert solver_metrics.pending_count() == 0
    assert "Could not save 1 solver request measurements" in caplog.text


@pytest.mark.asyncio
async def test_fanficfare_solver_requests_are_timed_individually(monkeypatch, sqlite_sessionmaker):
    from fanficfare import exceptions
    from fanficfare.fetchers.fetcher_flaresolverr_proxy import FlareSolverr_ProxyFetcher

    monkeypatch.setattr(solver_metrics, "SessionLocal", sqlite_sessionmaker)
    # monkeypatch restores the unwrapped method, so the wrapper does not leak into other tests.
    monkeypatch.setattr(FlareSolverr_ProxyFetcher, "request", FlareSolverr_ProxyFetcher.request)
    config = {
        "flaresolverr_proxy_address": "192.168.1.151",
        "flaresolverr_proxy_port": "8193",
        "flaresolverr_proxy_timeout": "59000",
    }
    replies = iter(
        [
            {"status": "ok", "solution": {"status": 200, "url": "u", "cookies": [], "response": "<html>chapter</html>"}},
            {"status": "error", "message": "Error solving the challenge."},
        ]
    )

    def do_fs_request(self, cmd, url=None, headers=None, parameters=None):
        reply = MagicMock()
        reply.json = next(replies)
        return reply

    monkeypatch.setattr(FlareSolverr_ProxyFetcher, "do_fs_request", do_fs_request)

    solver_metrics.install_fanficfare_timing()
    solver_metrics.install_fanficfare_timing()  # Installing twice must not time each request twice.
    fetcher = FlareSolverr_ProxyFetcher(lambda key, default=None: config.get(key, default), lambda key, default=None: [])

    assert fetcher.request("GET", "https://www.scribblehub.com/read/1/chapter/2/").content == "<html>chapter</html>"
    with pytest.raises(exceptions.HTTPErrorFFF):
        fetcher.request("GET", "https://www.scribblehub.com/read/1/chapter/3/")

    ok, failed = await _saved(sqlite_sessionmaker)
    assert (ok.site, ok.solver_url, ok.source, ok.success) == ("scribblehub.com", TRAWL, "fanficfare", True)
    assert (failed.success, failed.error_type) == (False, "HTTPErrorFFF")


@pytest.mark.asyncio
async def test_fanficfare_thread_saves_its_solver_requests(monkeypatch, sqlite_sessionmaker):
    monkeypatch.setattr(solver_metrics, "SessionLocal", sqlite_sessionmaker)
    monkeypatch.setattr(web_novel, "install_fanficfare_timing", lambda: None)

    def fanficfare_work() -> str:
        with solver_metrics.timed_solver_request("https://www.scribblehub.com/series/2/", TRAWL, "fanficfare"):
            return "done"

    assert await web_novel._run_fff_thread(fanficfare_work) == "done"

    async with sqlite_sessionmaker() as db:
        saved = (await db.scalars(select(models.SolverRequestMetric))).all()
    assert [row.site for row in saved] == ["scribblehub.com"]


@pytest.mark.asyncio
async def test_royalroad_solver_fallback_is_timed(monkeypatch, sqlite_sessionmaker):
    monkeypatch.setattr(solver_metrics, "SessionLocal", sqlite_sessionmaker)

    def refuse(*args, **kwargs):
        raise requests.ConnectionError("solver offline")

    monkeypatch.setattr(requests.Session, "post", refuse)
    challenged = requests.Response()
    challenged.url = "https://www.royalroad.com/fiction/1"

    with pytest.raises(royalroad_anubis.RoyalRoadChallengeError):
        royalroad_anubis._FlareSolverr(f"{FLARESOLVERR}/v1", 59_000).fetch(challenged)

    (failed,) = await _saved(sqlite_sessionmaker)
    assert (failed.site, failed.solver_url, failed.source, failed.success, failed.error_type) == (
        "royalroad.com",
        FLARESOLVERR,
        "royalroad",
        False,
        "RoyalRoadChallengeError",
    )


@pytest.mark.asyncio
async def test_cover_solver_requests_are_timed(monkeypatch, sqlite_sessionmaker):
    monkeypatch.setattr(solver_metrics, "SessionLocal", sqlite_sessionmaker)
    monkeypatch.setattr(cover_images, "validate_remote_cover_url", lambda url: None)
    replies = iter(
        [
            _solver_reply({"status": "ok", "solution": {"status": 200, "response": "<html></html>"}}),
            _solver_reply({"status": "ok", "solution": {"status": 403, "response": ""}}),
        ]
    )
    posted: list[str] = []

    def post(url, **kwargs):
        posted.append(url)
        return next(replies)

    monkeypatch.setattr(cover_images.http_requests, "post", post)
    site_config = {"flaresolverr_proxy_address": "192.168.1.151", "flaresolverr_proxy_port": "8193"}

    cover_images.fetch_page_via_flaresolverr("https://www.scribblehub.com/series/2/", site_config)
    with pytest.raises(ValueError):
        cover_images.fetch_page_via_flaresolverr("https://www.scribblehub.com/series/3/", site_config)

    ok, failed = await _saved(sqlite_sessionmaker)
    assert posted == [f"{TRAWL}/v1", f"{TRAWL}/v1"]
    assert (ok.site, ok.solver_url, ok.source, ok.success) == ("scribblehub.com", TRAWL, "cover", True)
    assert failed.success is False


@pytest.mark.asyncio
async def test_solver_summaries_separate_each_site_and_solver(db):
    now = datetime.now(timezone.utc)

    def metric(site: str, solver_url: str, duration_ms: float, *, success: bool = True, age_hours: float = 1):
        return models.SolverRequestMetric(
            site=site,
            solver_url=solver_url,
            source="fanficfare",
            success=success,
            duration_ms=duration_ms,
            error_type=None if success else "HTTPErrorFFF",
            created_at=now - timedelta(hours=age_hours),
        )

    db.add_all(
        [
            metric("scribblehub.com", FLARESOLVERR, 20_000, age_hours=48),
            metric("scribblehub.com", FLARESOLVERR, 0, success=False, age_hours=47),
            metric("scribblehub.com", TRAWL, 12_000, age_hours=3),
            metric("scribblehub.com", TRAWL, 13_000, age_hours=2),
            metric("royalroad.com", TRAWL, 500),
        ]
    )
    await db.commit()

    royalroad, old_solver, new_solver = await solver_metrics.solver_summaries(db)

    assert (royalroad.site, royalroad.solver_url, royalroad.requests) == ("royalroad.com", TRAWL, 1)
    assert (old_solver.site, old_solver.solver_url) == ("scribblehub.com", FLARESOLVERR)
    assert (old_solver.requests, old_solver.answered, old_solver.failed) == (2, 1, 1)
    assert old_solver.success_rate == 50.0
    assert old_solver.answered_24h == 0
    assert (new_solver.site, new_solver.solver_url) == ("scribblehub.com", TRAWL)
    assert new_solver.success_rate == 100.0
    assert new_solver.p50_ms == 12_500.0
    assert new_solver.p95_ms == 12_950.0
    assert new_solver.answered_24h == 2
    assert new_solver.average_24h_ms == 12_500.0
    assert new_solver.speed_buckets.from_5s_to_15s == 2


@pytest.mark.asyncio
async def test_endpoint_stats_api_includes_pending_solver_requests(monkeypatch, app_client, sqlite_sessionmaker):
    monkeypatch.setattr(solver_metrics, "SessionLocal", sqlite_sessionmaker)
    with solver_metrics.timed_solver_request("https://www.royalroad.com/fiction/1", TRAWL, "royalroad"):
        pass

    response = app_client.get("/api/audiobook/settings/endpoint-stats")

    assert response.status_code == 200
    (solver,) = response.json()["solver"]
    assert solver["site"] == "royalroad.com"
    assert solver["solver_url"] == TRAWL
    assert solver["requests"] == 1
    assert solver["success_rate"] == 100.0
    assert solver["last_answered_at"] is not None
