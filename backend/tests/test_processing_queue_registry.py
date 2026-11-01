"""Tests for the processing queue's job handler registry and lease reaper."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app import crud
from backend.app.models import ProcessingJob
from backend.app.services import processing_queue as processing_queue_module
from backend.app.services.processing_queue import JOB_HANDLERS, JOB_POLICIES, ProcessingQueue


def test_every_job_policy_has_a_handler():
    assert JOB_HANDLERS.keys() == JOB_POLICIES.keys()


@pytest.mark.asyncio
async def test_execute_dispatches_through_the_registry(monkeypatch):
    queue = ProcessingQueue()
    handler = AsyncMock(return_value="handled")
    monkeypatch.setitem(JOB_HANDLERS, "clean_all", handler)
    job = SimpleNamespace(job_type="clean_all", payload=None)

    assert await queue._execute(job) == "handled"
    handler.assert_awaited_once_with(queue, job)


@pytest.mark.asyncio
async def test_execute_rejects_unregistered_job_type(monkeypatch):
    monkeypatch.setattr(processing_queue_module, "validate_job_payload", lambda job_type, payload: None)
    with pytest.raises(ValueError, match="Unsupported processing job type: mystery"):
        await ProcessingQueue()._execute(SimpleNamespace(job_type="mystery", payload=None))


@pytest.mark.asyncio
async def test_worker_poll_does_not_run_lease_recovery(sqlite_sessionmaker, monkeypatch):
    barrier = SimpleNamespace(
        backup_active=False,
        wait_until_writes_allowed=AsyncMock(side_effect=[None, asyncio.CancelledError]),
    )
    recover = AsyncMock(return_value=(0, 0))
    monkeypatch.setattr(processing_queue_module, "SessionLocal", sqlite_sessionmaker)
    monkeypatch.setattr(processing_queue_module, "backup_barrier", barrier)
    monkeypatch.setattr(processing_queue_module.crud, "recover_abandoned_processing_jobs", recover)
    queue = ProcessingQueue()
    queue._poll_seconds = 0

    with pytest.raises(asyncio.CancelledError):
        await queue._run("cpu", 1)

    recover.assert_not_awaited()


@pytest.mark.asyncio
async def test_reaper_cancels_expired_leases_and_wakes_workers(sqlite_sessionmaker, monkeypatch):
    async with sqlite_sessionmaker() as db:
        await crud.create_processing_job(db, job_type="clean_all", resource_lane="cpu")
        job = await crud.claim_processing_job(db, resource_lane="cpu", lease_owner="lost-worker", lease_seconds=60)
        assert job is not None
        job_id = job.id
        job.cancel_requested = True
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()

    barrier = SimpleNamespace(
        backup_active=False,
        wait_until_writes_allowed=AsyncMock(side_effect=[None, asyncio.CancelledError]),
    )
    monkeypatch.setattr(processing_queue_module, "SessionLocal", sqlite_sessionmaker)
    monkeypatch.setattr(processing_queue_module, "backup_barrier", barrier)
    queue = ProcessingQueue()
    queue._reaper_seconds = 0

    with pytest.raises(asyncio.CancelledError):
        await queue._reap_abandoned_jobs()

    assert queue._wake.is_set()
    async with sqlite_sessionmaker() as db:
        reaped = await db.get(ProcessingJob, job_id)
        assert reaped.status == "canceled"
        assert reaped.lease_owner is None


@pytest.mark.asyncio
async def test_reaper_survives_database_errors(monkeypatch):
    barrier = SimpleNamespace(
        backup_active=False,
        wait_until_writes_allowed=AsyncMock(side_effect=[None, None, asyncio.CancelledError]),
    )
    monkeypatch.setattr(processing_queue_module, "backup_barrier", barrier)
    queue = ProcessingQueue()
    queue._reaper_seconds = 0
    recover = AsyncMock(side_effect=[RuntimeError("database unavailable"), 0])
    monkeypatch.setattr(queue, "_recover_abandoned_jobs", recover)

    with pytest.raises(asyncio.CancelledError):
        await queue._reap_abandoned_jobs()

    assert recover.await_count == 2
    assert not queue._wake.is_set()


@pytest.mark.asyncio
async def test_start_runs_one_reaper_and_stop_cancels_it(sqlite_sessionmaker, monkeypatch):
    audio = SimpleNamespace(start_background_audio=AsyncMock(), stop_background_audio=AsyncMock())
    monkeypatch.setattr(processing_queue_module, "get_audiobook_queue", lambda: audio)
    monkeypatch.setattr(processing_queue_module, "SessionLocal", sqlite_sessionmaker)
    queue = ProcessingQueue()

    await queue.start()
    try:
        reaper = queue._reaper_task
        assert reaper is not None and not reaper.done()
        assert queue.is_running
        assert queue.health_snapshot()["active_workers"] == len(queue._worker_tasks)
    finally:
        await queue.stop()

    assert reaper.cancelled()
    assert queue._reaper_task is None
    assert not queue.is_running
