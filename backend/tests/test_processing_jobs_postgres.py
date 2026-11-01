"""PostgreSQL-only behavior of the processing-job ledger: row locks, leases and the dedupe index.

SQLite has no ``SELECT ... FOR UPDATE SKIP LOCKED`` and serializes writers, so
the unit suite cannot show that two workers never claim the same job. These tests
run only when ``STORY_MANAGER_TEST_POSTGRES_URL`` names a throwaway database
migrated to head; ``make test-migrations`` sets it for its container. Every test
works in its own resource lane and deletes its rows afterwards.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app import crud
from backend.app.models import ProcessingJob

POSTGRES_URL = os.getenv("STORY_MANAGER_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not POSTGRES_URL, reason="set STORY_MANAGER_TEST_POSTGRES_URL to a migrated PostgreSQL database"),
]

# A claim that waits on another worker's row lock instead of skipping it would hang.
CLAIM_TIMEOUT_SECONDS = 5


@pytest_asyncio.fixture
async def pg():
    assert POSTGRES_URL is not None
    engine = create_async_engine(POSTGRES_URL, poolclass=NullPool)
    lane = f"pg-test-{uuid4().hex[:10]}"
    try:
        yield SimpleNamespace(
            sessionmaker=async_sessionmaker(engine, expire_on_commit=False),
            lane=lane,
        )
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(ProcessingJob).where(ProcessingJob.resource_lane == lane))
        await engine.dispose()


async def _queue(pg, count: int = 1, **fields) -> list[int]:
    ids = []
    async with pg.sessionmaker() as db:
        for _ in range(count):
            job, created = await crud.create_processing_job(db, job_type="clean_all", resource_lane=pg.lane, **fields)
            assert created
            ids.append(job.id)
    return ids


async def _claim(pg, owner: str, lease_seconds: int = 60) -> ProcessingJob | None:
    async with pg.sessionmaker() as db:
        return await asyncio.wait_for(
            crud.claim_processing_job(db, resource_lane=pg.lane, lease_owner=owner, lease_seconds=lease_seconds),
            CLAIM_TIMEOUT_SECONDS,
        )


@pytest.mark.asyncio
async def test_claim_skips_a_row_another_worker_has_locked(pg):
    first, second = await _queue(pg, 2)

    async with pg.sessionmaker() as holder:
        # Worker A is mid-claim on the oldest job and has not committed yet.
        locked = (
            await holder.execute(select(ProcessingJob.id).where(ProcessingJob.id == first).with_for_update())
        ).scalar_one()
        assert locked == first

        claimed = await _claim(pg, "worker-b")
        assert claimed is not None and claimed.id == second
        assert await _claim(pg, "worker-c") is None
        await holder.rollback()

    reclaimed = await _claim(pg, "worker-c")
    assert reclaimed is not None and reclaimed.id == first


@pytest.mark.asyncio
async def test_parallel_claims_never_hand_out_the_same_job(pg):
    queued = await _queue(pg, 5)

    claims = await asyncio.gather(*(_claim(pg, f"worker-{index}") for index in range(12)))

    claimed = [job for job in claims if job is not None]
    assert sorted(job.id for job in claimed) == sorted(queued)
    async with pg.sessionmaker() as db:
        rows = (await db.execute(select(ProcessingJob).where(ProcessingJob.resource_lane == pg.lane))).scalars().all()
    assert {row.status for row in rows} == {"running"}
    assert all(row.attempt_count == 1 for row in rows)
    assert {row.lease_owner for row in rows} == {job.lease_owner for job in claimed}


@pytest.mark.asyncio
async def test_expired_lease_moves_the_job_to_another_worker(pg):
    (job_id,) = await _queue(pg)
    first = await _claim(pg, "worker-a")
    assert first is not None and first.id == job_id

    # A live lease is not claimable, and its owner can extend it.
    assert await _claim(pg, "worker-b") is None
    async with pg.sessionmaker() as db:
        assert await crud.heartbeat_processing_job(db, job_id, lease_owner="worker-a", lease_seconds=60)

    async with pg.sessionmaker() as db:
        await db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        await db.commit()

    second = await _claim(pg, "worker-b")
    assert second is not None and second.id == job_id
    assert second.lease_owner == "worker-b"
    assert second.attempt_count == 2
    assert second.progress_detail == "Retry attempt 2"
    async with pg.sessionmaker() as db:
        # The worker that lost its lease can no longer keep the job alive.
        assert not await crud.heartbeat_processing_job(db, job_id, lease_owner="worker-a", lease_seconds=60)
        assert await crud.heartbeat_processing_job(db, job_id, lease_owner="worker-b", lease_seconds=60)


@pytest.mark.asyncio
async def test_exhausted_and_canceled_jobs_are_not_claimed(pg):
    exhausted, canceled = await _queue(pg, 2, max_attempts=1)
    async with pg.sessionmaker() as db:
        await db.execute(update(ProcessingJob).where(ProcessingJob.id == exhausted).values(attempt_count=1))
        await db.execute(update(ProcessingJob).where(ProcessingJob.id == canceled).values(cancel_requested=True))
        await db.commit()

    assert await _claim(pg, "worker-a") is None


@pytest.mark.asyncio
async def test_dedupe_index_allows_one_active_job_per_key(pg):
    dedupe_key = f"{pg.lane}:dedupe"
    async with pg.sessionmaker() as db:
        definition = (
            await db.execute(
                text("SELECT indexdef FROM pg_indexes WHERE tablename = 'processing_jobs' AND indexname = :name"),
                {"name": "uq_processing_jobs_active_dedupe"},
            )
        ).scalar_one()
    assert "UNIQUE" in definition
    assert "dedupe_key IS NOT NULL" in definition

    def job(status: str = "queued") -> ProcessingJob:
        return ProcessingJob(job_type="clean_all", resource_lane=pg.lane, dedupe_key=dedupe_key, status=status)

    async with pg.sessionmaker() as db:
        db.add(job())
        await db.commit()
        db.add(job())
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

        # Finished jobs fall outside the partial index, so history may repeat the key.
        await db.execute(update(ProcessingJob).where(ProcessingJob.dedupe_key == dedupe_key).values(status="completed"))
        await db.commit()
        db.add(job("completed"))
        db.add(job())
        await db.commit()

        statuses = (await db.execute(select(ProcessingJob.status).where(ProcessingJob.dedupe_key == dedupe_key))).scalars()
        assert sorted(statuses) == ["completed", "completed", "queued"]


@pytest.mark.asyncio
async def test_concurrent_creates_with_one_dedupe_key_share_one_job(pg):
    dedupe_key = f"{pg.lane}:race"

    async def create() -> tuple[int, bool]:
        async with pg.sessionmaker() as db:
            job, created = await crud.create_processing_job(
                db, job_type="clean_all", resource_lane=pg.lane, dedupe_key=dedupe_key
            )
            return job.id, created

    results = await asyncio.gather(*(create() for _ in range(8)))

    assert len({job_id for job_id, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    async with pg.sessionmaker() as db:
        rows = (await db.execute(select(ProcessingJob.id).where(ProcessingJob.dedupe_key == dedupe_key))).scalars()
        assert len(list(rows)) == 1
