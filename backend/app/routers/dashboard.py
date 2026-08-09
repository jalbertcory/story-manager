"""Aggregated, actionable library attention signals."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..config import LIBRARY_PATH
from ..database import get_db
from ..services.library_health import find_missing_covers, inspect_library_files

router = APIRouter()


def _book_item(book: models.Book, issue: str, detail: str | None = None) -> schemas.AttentionBookItem:
    return schemas.AttentionBookItem(
        book_id=book.id,
        title=book.title,
        author=book.author,
        issue=issue,
        detail=detail,
    )


async def _failed_jobs(db: AsyncSession, limit: int) -> schemas.AttentionJobCategory:
    scope = (
        models.ProcessingJob.job_type,
        func.coalesce(models.ProcessingJob.book_id, -1),
        func.coalesce(models.ProcessingJob.target_type, ""),
        func.coalesce(models.ProcessingJob.target_id, -1),
    )
    ranked_jobs = select(
        models.ProcessingJob.id.label("job_id"),
        func.row_number()
        .over(
            partition_by=scope,
            order_by=(models.ProcessingJob.created_at.desc(), models.ProcessingJob.id.desc()),
        )
        .label("recency"),
    ).subquery()
    latest_job_ids = select(ranked_jobs.c.job_id).where(ranked_jobs.c.recency == 1)
    latest_failures = (
        models.ProcessingJob.status == "error",
        models.ProcessingJob.id.in_(latest_job_ids),
    )
    count = await db.scalar(select(func.count()).select_from(models.ProcessingJob).where(*latest_failures))
    rows = (
        await db.execute(
            select(models.ProcessingJob, models.Book.title)
            .outerjoin(models.Book, models.ProcessingJob.book_id == models.Book.id)
            .where(*latest_failures)
            .order_by(models.ProcessingJob.created_at.desc(), models.ProcessingJob.id.desc())
            .limit(limit)
        )
    ).all()
    return schemas.AttentionJobCategory(
        count=count or 0,
        items=[
            schemas.AttentionJobItem(
                id=job.id,
                job_type=job.job_type,
                book_id=job.book_id,
                book_title=book_title,
                error=job.error,
                completed_at=job.completed_at,
            )
            for job, book_title in rows
        ],
    )


async def _failed_refreshes(db: AsyncSession, limit: int) -> schemas.AttentionBookCategory:
    query = (
        select(models.Book)
        .where(models.Book.refresh_status == "error")
        .order_by(models.Book.updated_at.desc(), models.Book.id.desc())
    )
    count = await db.scalar(select(func.count()).select_from(query.subquery()))
    books = list((await db.execute(query.limit(limit))).scalars().all())
    return schemas.AttentionBookCategory(
        count=count or 0,
        items=[_book_item(book, "refresh_failed", "The most recent source refresh failed.") for book in books],
    )


async def _stale_audiobooks(db: AsyncSession, limit: int) -> schemas.AttentionBookCategory:
    ai_query = select(models.Book).where(
        models.Book.audiobook_enabled.is_(True),
        models.Book.audiobook_publication_state == "stale",
    )
    human_query = (
        select(models.Book, models.ImportedAudiobook)
        .join(models.ImportedAudiobook, models.ImportedAudiobook.book_id == models.Book.id)
        .where(models.ImportedAudiobook.status == "stale")
    )

    reasons: dict[int, list[str]] = defaultdict(list)
    books_by_id: dict[int, models.Book] = {}
    for book in (await db.execute(ai_query)).scalars().all():
        books_by_id[book.id] = book
        reasons[book.id].append("Generated audiobook")
    for book, edition in (await db.execute(human_query)).all():
        books_by_id[book.id] = book
        reasons[book.id].append(edition.name or "Imported audiobook")

    ordered = sorted(
        books_by_id.values(), key=lambda book: (book.updated_at is not None, book.updated_at, book.id), reverse=True
    )
    return schemas.AttentionBookCategory(
        count=len(ordered),
        items=[
            _book_item(book, "audiobook_stale", f"{', '.join(reasons[book.id])} needs reconciliation with the current text.")
            for book in ordered[:limit]
        ],
    )


async def _metadata_proposals(db: AsyncSession, limit: int) -> schemas.AttentionMetadataCategory:
    count = await db.scalar(
        select(func.count()).select_from(models.MetadataProposal).where(models.MetadataProposal.status == "open")
    )
    rows = (
        await db.execute(
            select(models.MetadataProposal, models.Book)
            .join(models.Book, models.MetadataProposal.book_id == models.Book.id)
            .where(models.MetadataProposal.status == "open")
            .order_by(models.MetadataProposal.created_at.desc(), models.MetadataProposal.id.desc())
            .limit(limit)
        )
    ).all()
    return schemas.AttentionMetadataCategory(
        count=count or 0,
        items=[
            schemas.AttentionMetadataItem(
                proposal_id=proposal.id,
                book_id=book.id,
                title=book.title,
                author=book.author,
                note=proposal.note,
            )
            for proposal, book in rows
        ],
    )


@router.get("/api/dashboard/attention", response_model=schemas.AttentionDashboard)
async def get_attention_dashboard(
    limit: int = Query(5, ge=1, le=25),
    db: AsyncSession = Depends(get_db),
) -> schemas.AttentionDashboard:
    books = await crud.get_books(db, limit=100000)
    file_issues = inspect_library_files(books, library_path=LIBRARY_PATH)
    broken_files = [
        issue
        for issue in file_issues
        if issue["issue"]
        in {"missing_immutable_path", "immutable_file_not_found", "missing_current_path", "current_file_not_found"}
    ]
    missing_covers = find_missing_covers(books, library_path=LIBRARY_PATH)

    failed_jobs = await _failed_jobs(db, limit)
    failed_refreshes = await _failed_refreshes(db, limit)
    stale_audiobooks = await _stale_audiobooks(db, limit)
    metadata_proposals = await _metadata_proposals(db, limit)
    broken_category = schemas.AttentionFileCategory(
        count=len(broken_files),
        items=[schemas.AttentionFileItem(**issue) for issue in broken_files[:limit]],
    )
    cover_category = schemas.AttentionFileCategory(
        count=len(missing_covers),
        items=[schemas.AttentionFileItem(**issue) for issue in missing_covers[:limit]],
    )
    total_count = sum(
        category.count
        for category in (
            failed_jobs,
            failed_refreshes,
            stale_audiobooks,
            metadata_proposals,
            broken_category,
            cover_category,
        )
    )
    return schemas.AttentionDashboard(
        total_count=total_count,
        failed_jobs=failed_jobs,
        failed_refreshes=failed_refreshes,
        stale_audiobooks=stale_audiobooks,
        metadata_proposals=metadata_proposals,
        broken_files=broken_category,
        missing_covers=cover_category,
    )
