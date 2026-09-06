"""Web novel endpoints: add from URL, queue imports, and refresh from source."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..database import get_db
from ..lifecycle import WEB_REFRESH, WebRefreshStatus, transition_state
from ..services.processing_queue import queue_processing_job
from ..services.refresh_queue import RefreshQueue, get_refresh_queue

logger = logging.getLogger(__name__)

router = APIRouter()


class WebNovelRequest(BaseModel):
    url: HttpUrl


@router.post(
    "/api/books/add_web_novel",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.Book,
)
async def add_web_novel(
    request: WebNovelRequest,
    db: AsyncSession = Depends(get_db),
) -> models.Book:
    """Creates a pending book record immediately and queues the download."""
    source_url_str = str(request.url)
    existing_book = await crud.get_book_by_source_url(db, source_url=source_url_str)
    if existing_book:
        if existing_book.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This source is in the recycle bin. Restore it or permanently delete it before importing again.",
            )
        if (
            existing_book.source_type == models.SourceType.web
            and existing_book.download_status == "error"
            and not existing_book.immutable_path
            and not existing_book.current_path
        ):
            logger.info("Retrying failed web import placeholder for %s (book_id=%s).", source_url_str, existing_book.id)
            retried_book = await crud.reset_failed_web_book_for_retry(db, existing_book, source_url_str)
            await queue_processing_job(
                db=db,
                job_type="import_web_book",
                book_id=retried_book.id,
                target_type="book",
                target_id=retried_book.id,
                payload={"source_url": source_url_str},
                dedupe_key=f"import_web_book:book:{retried_book.id}",
                progress_detail="Queued web book import retry",
            )
            return retried_book
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Book from URL {source_url_str} already exists in the library.",
        )

    book_to_create = schemas.BookCreate(
        title=source_url_str,
        author="Pending",
        source_url=request.url,
        source_type=models.SourceType.web,
        download_status="pending",
    )
    db_book = await crud.create_book(db=db, book=book_to_create)
    await queue_processing_job(
        db=db,
        job_type="import_web_book",
        book_id=db_book.id,
        target_type="book",
        target_id=db_book.id,
        payload={"source_url": source_url_str},
        dedupe_key=f"import_web_book:book:{db_book.id}",
        progress_detail="Queued web book import",
    )
    return db_book


@router.post(
    "/api/books/{book_id}/refresh",
    response_model=schemas.Book,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_book(
    book_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> models.Book:
    """Queue a background refresh of a web novel from its source URL.

    Returns 202 Accepted immediately with the book's updated ``refresh_status``.
    Clients should poll ``GET /api/books/{book_id}`` until ``refresh_status`` is
    null (success) or ``"error"``. The actual work — re-downloading via
    FanFicFare, rebuilding the cleaned EPUB, re-syncing metadata — runs as a
    durable processing job in the same flow used by the scheduled update.
    """
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if not db_book.source_url:
        raise HTTPException(status_code=400, detail="Book does not have a source URL to refresh from.")

    # If a refresh is already queued/running for this book, treat the request as a
    # no-op rather than doubling it up — return the current status so the client
    # can begin polling.
    if db_book.refresh_status not in ("queued", "processing"):
        transition_state(db_book, "refresh_status", WEB_REFRESH, WebRefreshStatus.QUEUED, context=f"book {db_book.id}")
        await db.commit()
        await db.refresh(db_book)

    job = await queue_processing_job(
        db=db,
        job_type="refresh_book",
        book_id=db_book.id,
        target_type="book",
        target_id=db_book.id,
        target_content_version=db_book.content_version,
        dedupe_key=f"refresh_book:book:{db_book.id}",
        progress_detail="Queued from Refresh From Source",
    )
    legacy_queue = get_refresh_queue()
    if not isinstance(legacy_queue, RefreshQueue):
        await legacy_queue.enqueue(db_book.id)
    response.headers["X-Processing-Job-Id"] = str(job.id)
    return db_book


@router.post("/api/books/{book_id}/detach-source", response_model=schemas.Book)
async def detach_book_source(book_id: int, db: AsyncSession = Depends(get_db)) -> models.Book:
    """Remove a book's web/source URL metadata and treat it as a normal EPUB."""
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if not db_book.source_url and db_book.source_type != models.SourceType.web:
        raise HTTPException(status_code=400, detail="Book does not have a web source to remove.")
    if not db_book.immutable_path or not db_book.current_path:
        raise HTTPException(
            status_code=400,
            detail="Book must have EPUB files before its web source can be removed.",
        )

    return await crud.detach_book_source(db, db_book)
