"""Metadata sync jobs, matches, and proposal CRUD operations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import asc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .. import models


async def create_metadata_sync_job(
    db: AsyncSession,
    *,
    trigger: str,
    book_ids: list[int],
) -> models.MetadataSyncJob:
    job = models.MetadataSyncJob(
        trigger=trigger,
        status="queued",
        total_books=len(book_ids),
        processed_books=0,
        matched_books=0,
        proposed_books=0,
        applied_books=0,
        scope={"book_ids": book_ids},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_metadata_sync_job(db: AsyncSession, job_id: int) -> Optional[models.MetadataSyncJob]:
    result = await db.execute(select(models.MetadataSyncJob).where(models.MetadataSyncJob.id == job_id))
    return result.scalars().first()


async def get_latest_metadata_sync_job(db: AsyncSession) -> Optional[models.MetadataSyncJob]:
    result = await db.execute(select(models.MetadataSyncJob).order_by(models.MetadataSyncJob.created_at.desc()).limit(1))
    return result.scalars().first()


async def get_pending_metadata_sync_jobs(db: AsyncSession) -> list[models.MetadataSyncJob]:
    result = await db.execute(
        select(models.MetadataSyncJob)
        .where(models.MetadataSyncJob.status == "queued")
        .order_by(asc(models.MetadataSyncJob.created_at))
    )
    return result.scalars().all()


async def reset_running_metadata_sync_jobs(db: AsyncSession) -> None:
    result = await db.execute(select(models.MetadataSyncJob).where(models.MetadataSyncJob.status == "running"))
    jobs = result.scalars().all()
    for job in jobs:
        job.status = "queued"
        job.started_at = None
        job.completed_at = None
        job.error = None
    if jobs:
        await db.commit()


async def mark_metadata_sync_job_running(db: AsyncSession, job: models.MetadataSyncJob) -> models.MetadataSyncJob:
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    job.completed_at = None
    job.error = None
    await db.commit()
    await db.refresh(job)
    return job


async def mark_metadata_sync_job_progress(
    db: AsyncSession,
    job: models.MetadataSyncJob,
    *,
    processed_increment: int = 0,
    matched_increment: int = 0,
    proposed_increment: int = 0,
    applied_increment: int = 0,
) -> models.MetadataSyncJob:
    job.processed_books += processed_increment
    job.matched_books += matched_increment
    job.proposed_books += proposed_increment
    job.applied_books += applied_increment
    await db.commit()
    await db.refresh(job)
    return job


async def complete_metadata_sync_job(db: AsyncSession, job: models.MetadataSyncJob) -> models.MetadataSyncJob:
    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(job)
    return job


async def fail_metadata_sync_job(db: AsyncSession, job: models.MetadataSyncJob, error: str) -> models.MetadataSyncJob:
    job.status = "failed"
    job.error = error
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(job)
    return job


async def get_metadata_match_by_book_id(db: AsyncSession, book_id: int) -> Optional[models.BookMetadataMatch]:
    result = await db.execute(
        select(models.BookMetadataMatch)
        .where(models.BookMetadataMatch.book_id == book_id)
        .order_by(models.BookMetadataMatch.match_confidence.desc().nullslast(), models.BookMetadataMatch.id.desc())
        .limit(1)
    )
    return result.scalars().first()


async def get_metadata_matches_by_book_id(db: AsyncSession, book_id: int) -> list[models.BookMetadataMatch]:
    result = await db.execute(
        select(models.BookMetadataMatch)
        .where(models.BookMetadataMatch.book_id == book_id)
        .order_by(models.BookMetadataMatch.match_confidence.desc().nullslast(), models.BookMetadataMatch.id.desc())
    )
    return result.scalars().all()


async def get_metadata_match(db: AsyncSession, match_id: int) -> Optional[models.BookMetadataMatch]:
    result = await db.execute(select(models.BookMetadataMatch).where(models.BookMetadataMatch.id == match_id))
    return result.scalars().first()


async def get_metadata_proposal_by_book_id(db: AsyncSession, book_id: int) -> Optional[models.MetadataProposal]:
    result = await db.execute(select(models.MetadataProposal).where(models.MetadataProposal.book_id == book_id))
    return result.scalars().first()


async def get_metadata_proposal(db: AsyncSession, proposal_id: int) -> Optional[models.MetadataProposal]:
    result = await db.execute(select(models.MetadataProposal).where(models.MetadataProposal.id == proposal_id))
    return result.scalars().first()


async def get_metadata_inbox_entries(
    db: AsyncSession,
    limit: int = 100,
) -> list[tuple[models.MetadataProposal, models.Book, Optional[models.BookMetadataMatch], list[models.BookMetadataMatch]]]:
    result = await db.execute(
        select(models.MetadataProposal, models.Book, models.BookMetadataMatch)
        .join(models.Book, models.MetadataProposal.book_id == models.Book.id)
        .outerjoin(models.BookMetadataMatch, models.MetadataProposal.match_id == models.BookMetadataMatch.id)
        .where(models.MetadataProposal.status == "open")
        .order_by(models.MetadataProposal.created_at.desc(), models.MetadataProposal.id.desc())
        .limit(limit)
    )
    rows = result.all()
    entries = []
    for proposal, book, match in rows:
        candidates = await get_metadata_matches_by_book_id(db, book.id)
        entries.append((proposal, book, match, candidates))
    return entries


async def get_stale_books_for_metadata_sync(
    db: AsyncSession,
    *,
    stale_after_days: int,
    limit: int = 100000,
) -> list[models.Book]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=stale_after_days)
    result = await db.execute(
        select(models.Book)
        .where(
            models.Book.author.is_not(None),
            func.lower(models.Book.author) != "pending",
            models.Book.title.is_not(None),
            (models.Book.metadata_synced_at.is_(None) | (models.Book.metadata_synced_at <= cutoff)),
        )
        .order_by(asc(models.Book.id))
        .limit(limit)
    )
    return result.scalars().all()
