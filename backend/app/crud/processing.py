"""CRUD operations for the durable processing-job ledger."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Book, ProcessingJob

ACTIVE_PROCESSING_STATUSES = ("queued", "running")


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
    progress_detail: str | None = "Queued",
) -> tuple[ProcessingJob, bool]:
    """Create a queued job, returning an active duplicate when one exists."""
    if dedupe_key:
        result = await db.execute(
            select(ProcessingJob)
            .where(
                ProcessingJob.dedupe_key == dedupe_key,
                ProcessingJob.status == "queued",
            )
            .order_by(desc(ProcessingJob.id))
        )
        existing = result.scalars().first()
        if existing is not None:
            return existing, False

    job = ProcessingJob(
        job_type=job_type,
        status="queued",
        book_id=book_id,
        target_type=target_type,
        target_id=target_id,
        target_content_version=target_content_version,
        parent_job_id=parent_job_id,
        payload=payload or {},
        dedupe_key=dedupe_key,
        progress_detail=progress_detail,
    )
    db.add(job)
    await db.commit()
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


async def get_pending_processing_jobs(db: AsyncSession) -> list[ProcessingJob]:
    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.status.in_(ACTIVE_PROCESSING_STATUSES))
        .order_by(ProcessingJob.created_at, ProcessingJob.id)
    )
    jobs = list(result.scalars().all())
    for job in jobs:
        if job.status == "running":
            job.status = "queued"
            job.progress_detail = "Queued after restart"
            job.started_at = None
    if jobs:
        await db.commit()
    return jobs


async def mark_processing_job_running(db: AsyncSession, job_id: int) -> ProcessingJob | None:
    job = await db.get(ProcessingJob, job_id)
    if job is None or job.status != "queued":
        return None
    if job.cancel_requested:
        job.status = "canceled"
        job.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return None
    job.status = "running"
    job.attempt_count = (job.attempt_count or 0) + 1
    job.started_at = datetime.now(timezone.utc)
    job.completed_at = None
    job.error = None
    await db.commit()
    await db.refresh(job)
    return job


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


async def complete_processing_job(db: AsyncSession, job_id: int, detail: str | None = None) -> None:
    job = await db.get(ProcessingJob, job_id)
    if job is None:
        return
    job.status = "completed"
    job.cancel_requested = False
    job.completed_at = datetime.now(timezone.utc)
    if detail is not None:
        job.progress_detail = detail
    if job.progress_total:
        job.progress_current = job.progress_total
    await db.commit()


async def fail_processing_job(db: AsyncSession, job_id: int, error: str) -> None:
    job = await db.get(ProcessingJob, job_id)
    if job is None:
        return
    job.status = "error"
    job.error = error
    job.progress_detail = "Failed"
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()


async def mark_processing_job_canceled(db: AsyncSession, job_id: int) -> None:
    job = await db.get(ProcessingJob, job_id)
    if job is None:
        return
    job.status = "canceled"
    job.progress_detail = "Canceled"
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()


async def request_processing_job_cancel(db: AsyncSession, job_id: int) -> ProcessingJob | None:
    job = await db.get(ProcessingJob, job_id)
    if job is None:
        return None
    if job.status == "queued":
        job.status = "canceled"
        job.cancel_requested = True
        job.progress_detail = "Canceled"
        job.completed_at = datetime.now(timezone.utc)
    elif job.status == "running":
        job.cancel_requested = True
        job.progress_detail = "Cancellation requested"
    await db.commit()
    await db.refresh(job)
    return job


async def retry_processing_job(db: AsyncSession, job_id: int) -> ProcessingJob | None:
    job = await db.get(ProcessingJob, job_id)
    if job is None or job.status not in ("error", "canceled"):
        return None
    job.status = "queued"
    job.cancel_requested = False
    job.error = None
    job.started_at = None
    job.completed_at = None
    job.progress_current = 0
    job.progress_detail = "Queued for retry"
    await db.commit()
    await db.refresh(job)
    return job


async def is_processing_job_cancel_requested(db: AsyncSession, job_id: int) -> bool:
    job = await db.get(ProcessingJob, job_id)
    return job is None or bool(job.cancel_requested)
