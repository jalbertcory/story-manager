"""CRUD operations for the durable processing-job ledger."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable
from uuid import uuid4

from sqlalchemy import and_, desc, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..lifecycle import PROCESSING_JOB, ProcessingJobStatus, transition_state
from ..models import Book, ProcessingJob
from ..observability_context import request_id_var

ACTIVE_PROCESSING_STATUSES = tuple(PROCESSING_JOB.active_states)


async def create_processing_job(
    db: AsyncSession,
    *,
    job_type: str,
    book_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    target_content_version: int | None = None,
    parent_job_id: int | None = None,
    payload: dict | None = None,
    dedupe_key: str | None = None,
    resource_lane: str = "maintenance",
    max_attempts: int = 3,
    progress_detail: str | None = "Queued",
) -> tuple[ProcessingJob, bool]:
    """Create a queued job, returning an active duplicate when one exists."""
    if dedupe_key:
        result = await db.execute(
            select(ProcessingJob)
            .where(
                ProcessingJob.dedupe_key == dedupe_key,
                ProcessingJob.status.in_(ACTIVE_PROCESSING_STATUSES),
            )
            .order_by(desc(ProcessingJob.id))
        )
        existing = result.scalars().first()
        if existing is not None:
            return existing, False

    job = ProcessingJob(
        job_type=job_type,
        status=ProcessingJobStatus.QUEUED.value,
        book_id=book_id,
        target_type=target_type,
        target_id=target_id,
        target_content_version=target_content_version,
        parent_job_id=parent_job_id,
        request_id=request_id_var.get() or uuid4().hex[:12],
        payload=payload or {},
        dedupe_key=dedupe_key,
        resource_lane=resource_lane,
        max_attempts=max_attempts,
        progress_detail=progress_detail,
    )
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if not dedupe_key:
            raise
        existing = (
            (
                await db.execute(
                    select(ProcessingJob)
                    .where(
                        ProcessingJob.dedupe_key == dedupe_key,
                        ProcessingJob.status.in_(ACTIVE_PROCESSING_STATUSES),
                    )
                    .order_by(desc(ProcessingJob.id))
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            raise
        return existing, False
    await db.refresh(job)
    return job, True


async def get_processing_job(db: AsyncSession, job_id: int) -> ProcessingJob | None:
    return await db.get(ProcessingJob, job_id)


async def get_processing_jobs(
    db: AsyncSession,
    *,
    statuses: Iterable[str] | None = None,
    job_type: str | None = None,
    book_id: int | None = None,
    limit: int = 100,
) -> list[tuple[ProcessingJob, str | None]]:
    query = (
        select(ProcessingJob, Book.title)
        .outerjoin(Book, ProcessingJob.book_id == Book.id)
        .order_by(desc(ProcessingJob.created_at), desc(ProcessingJob.id))
        .limit(limit)
    )
    if statuses:
        query = query.where(ProcessingJob.status.in_(tuple(statuses)))
    if job_type:
        query = query.where(ProcessingJob.job_type == job_type)
    if book_id is not None:
        query = query.where(ProcessingJob.book_id == book_id)
    result = await db.execute(query)
    return list(result.all())


async def claim_processing_job(
    db: AsyncSession,
    *,
    resource_lane: str,
    lease_owner: str,
    lease_seconds: int,
) -> ProcessingJob | None:
    """Atomically claim the oldest runnable job in a resource lane."""
    now = datetime.now(timezone.utc)
    runnable = or_(
        and_(ProcessingJob.status == ProcessingJobStatus.QUEUED.value, ProcessingJob.available_at <= now),
        and_(ProcessingJob.status == ProcessingJobStatus.RUNNING.value, ProcessingJob.lease_expires_at <= now),
    )
    query = (
        select(ProcessingJob)
        .where(
            ProcessingJob.resource_lane == resource_lane,
            ProcessingJob.cancel_requested.is_(False),
            ProcessingJob.attempt_count < ProcessingJob.max_attempts,
            runnable,
        )
        .order_by(ProcessingJob.available_at, ProcessingJob.created_at, ProcessingJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = (await db.execute(query)).scalar_one_or_none()
    if job is None:
        await db.rollback()
        return None

    transition_state(job, "status", PROCESSING_JOB, ProcessingJobStatus.RUNNING, context=f"processing job {job.id}")
    job.attempt_count = (job.attempt_count or 0) + 1
    job.started_at = now
    job.completed_at = None
    job.error = None
    job.lease_owner = lease_owner
    job.heartbeat_at = now
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.progress_detail = "Running" if job.attempt_count == 1 else f"Retry attempt {job.attempt_count}"
    await db.commit()
    await db.refresh(job)
    return job


async def heartbeat_processing_job(
    db: AsyncSession,
    job_id: int,
    *,
    lease_owner: str,
    lease_seconds: int,
) -> bool:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.status == ProcessingJobStatus.RUNNING.value,
            ProcessingJob.lease_owner == lease_owner,
        )
        .values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds))
    )
    await db.commit()
    return bool(result.rowcount)


async def defer_processing_job_for_backup(db: AsyncSession, job_id: int, *, lease_owner: str) -> bool:
    """Return a just-claimed job to the queue when the backup barrier won the race."""
    job = await db.get(ProcessingJob, job_id)
    if job is None or job.status != ProcessingJobStatus.RUNNING.value or job.lease_owner != lease_owner:
        return False
    transition_state(job, "status", PROCESSING_JOB, ProcessingJobStatus.QUEUED, context=f"processing job {job.id}")
    job.attempt_count = max(0, (job.attempt_count or 0) - 1)
    job.started_at = None
    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    job.progress_detail = "Waiting for library backup to finish"
    await db.commit()
    return True


async def recover_abandoned_processing_jobs(db: AsyncSession) -> tuple[int, int]:
    """Cancel or exhaust expired leases; claimable jobs remain available to workers."""
    now = datetime.now(timezone.utc)
    canceled = await db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.status == ProcessingJobStatus.RUNNING.value,
            ProcessingJob.lease_expires_at <= now,
            ProcessingJob.cancel_requested.is_(True),
        )
        .values(
            status=ProcessingJobStatus.CANCELED.value,
            progress_detail="Canceled after worker lease expired",
            completed_at=now,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
        )
    )
    exhausted = await db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.status == ProcessingJobStatus.RUNNING.value,
            ProcessingJob.lease_expires_at <= now,
            ProcessingJob.cancel_requested.is_(False),
            ProcessingJob.attempt_count >= ProcessingJob.max_attempts,
        )
        .values(
            status=ProcessingJobStatus.ERROR.value,
            error="Worker lease expired and the retry limit was reached.",
            progress_detail="Failed after worker interruption",
            completed_at=now,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
        )
    )
    await db.commit()
    return canceled.rowcount or 0, exhausted.rowcount or 0


async def update_processing_job_progress(
    db: AsyncSession,
    job_id: int,
    *,
    current: int | None = None,
    total: int | None = None,
    detail: str | None = None,
) -> None:
    job = await db.get(ProcessingJob, job_id)
    if job is None:
        return
    if current is not None:
        job.progress_current = current
    if total is not None:
        job.progress_total = total
    if detail is not None:
        job.progress_detail = detail
    await db.commit()


async def complete_processing_job(
    db: AsyncSession,
    job_id: int,
    detail: str | None = None,
    *,
    lease_owner: str | None = None,
) -> bool:
    job = await db.get(ProcessingJob, job_id)
    if job is None or (lease_owner is not None and job.lease_owner != lease_owner):
        return False
    transition_state(job, "status", PROCESSING_JOB, ProcessingJobStatus.COMPLETED, context=f"processing job {job.id}")
    job.cancel_requested = False
    job.completed_at = datetime.now(timezone.utc)
    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    if detail is not None:
        job.progress_detail = detail
    if job.progress_total:
        job.progress_current = job.progress_total
    await db.commit()
    return True


async def fail_processing_job(
    db: AsyncSession,
    job_id: int,
    error: str,
    *,
    lease_owner: str | None = None,
    retry_backoff_seconds: int = 5,
) -> str | None:
    job = await db.get(ProcessingJob, job_id)
    if job is None or (lease_owner is not None and job.lease_owner != lease_owner):
        return None
    now = datetime.now(timezone.utc)
    job.error = error
    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    if job.cancel_requested:
        transition_state(job, "status", PROCESSING_JOB, ProcessingJobStatus.CANCELED, context=f"processing job {job.id}")
        job.progress_detail = "Canceled"
        job.completed_at = now
    elif job.attempt_count < job.max_attempts:
        delay = retry_backoff_seconds * (2 ** max(0, job.attempt_count - 1))
        transition_state(job, "status", PROCESSING_JOB, ProcessingJobStatus.QUEUED, context=f"processing job {job.id}")
        job.available_at = now + timedelta(seconds=delay)
        job.progress_detail = f"Retrying in {delay} seconds"
        job.completed_at = None
    else:
        transition_state(job, "status", PROCESSING_JOB, ProcessingJobStatus.ERROR, context=f"processing job {job.id}")
        job.progress_detail = "Failed"
        job.completed_at = now
    await db.commit()
    return job.status


async def mark_processing_job_canceled(db: AsyncSession, job_id: int) -> None:
    job = await db.get(ProcessingJob, job_id)
    if job is None:
        return
    transition_state(job, "status", PROCESSING_JOB, ProcessingJobStatus.CANCELED, context=f"processing job {job.id}")
    job.progress_detail = "Canceled"
    job.completed_at = datetime.now(timezone.utc)
    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    await db.commit()


async def request_processing_job_cancel(db: AsyncSession, job_id: int) -> ProcessingJob | None:
    job = await db.get(ProcessingJob, job_id)
    if job is None:
        return None
    if job.status == ProcessingJobStatus.QUEUED.value:
        transition_state(job, "status", PROCESSING_JOB, ProcessingJobStatus.CANCELED, context=f"processing job {job.id}")
        job.cancel_requested = True
        job.progress_detail = "Canceled"
        job.completed_at = datetime.now(timezone.utc)
    elif job.status == ProcessingJobStatus.RUNNING.value:
        job.cancel_requested = True
        job.progress_detail = "Cancellation requested"
    await db.commit()
    await db.refresh(job)
    return job


async def retry_processing_job(db: AsyncSession, job_id: int) -> ProcessingJob | None:
    job = await db.get(ProcessingJob, job_id)
    if job is None or job.status not in (ProcessingJobStatus.ERROR.value, ProcessingJobStatus.CANCELED.value):
        return None
    if job.dedupe_key:
        active = (
            await db.execute(
                select(ProcessingJob.id).where(
                    ProcessingJob.id != job.id,
                    ProcessingJob.dedupe_key == job.dedupe_key,
                    ProcessingJob.status.in_(ACTIVE_PROCESSING_STATUSES),
                )
            )
        ).scalar_one_or_none()
        if active is not None:
            return None
    transition_state(job, "status", PROCESSING_JOB, ProcessingJobStatus.QUEUED, context=f"processing job {job.id}")
    job.cancel_requested = False
    job.error = None
    job.started_at = None
    job.completed_at = None
    job.progress_current = 0
    job.progress_detail = "Queued for retry"
    job.attempt_count = 0
    job.available_at = datetime.now(timezone.utc)
    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return None
    await db.refresh(job)
    return job


async def is_processing_job_cancel_requested(db: AsyncSession, job_id: int) -> bool:
    job = await db.get(ProcessingJob, job_id)
    return job is None or bool(job.cancel_requested)
