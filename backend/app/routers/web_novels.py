"""Web novel endpoints: add from URL, queue imports, and refresh from source."""

import logging
import shutil

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, epub_editor, models, schemas
from ..config import LIBRARY_PATH
from ..database import get_db
from ..services.epub_utils import get_epub_word_and_chapter_count
from ..services.library_paths import build_book_paths
from ..services.metadata_jobs import queue_metadata_sync_job
from ..services.web_import_queue import get_web_import_queue
from ..services.web_novel import download_web_novel

logger = logging.getLogger(__name__)

router = APIRouter()


class WebNovelRequest(BaseModel):
    url: schemas.HttpUrl


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
    queue = get_web_import_queue()

    existing_book = await crud.get_book_by_source_url(db, source_url=source_url_str)
    if existing_book:
        if (
            existing_book.source_type == models.SourceType.web
            and existing_book.download_status == "error"
            and not existing_book.immutable_path
            and not existing_book.current_path
        ):
            logger.info("Retrying failed web import placeholder for %s (book_id=%s).", source_url_str, existing_book.id)
            retried_book = await crud.reset_failed_web_book_for_retry(db, existing_book, source_url_str)
            await queue.enqueue(retried_book.id, source_url_str)
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
    await queue.enqueue(db_book.id, source_url_str)
    return db_book


@router.post("/api/books/{book_id}/refresh", response_model=schemas.Book)
async def refresh_book(book_id: int, db: AsyncSession = Depends(get_db)) -> models.Book:
    """Re-downloads a web novel from its source URL and applies cleaning."""
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if not db_book.source_url:
        raise HTTPException(status_code=400, detail="Book does not have a source URL to refresh from.")

    if not db_book.immutable_path or not db_book.current_path:
        result = await download_web_novel(db_book.source_url, overwrite=True)
        if result is None:
            raise HTTPException(status_code=500, detail="FanFicFare did not produce a refreshed EPUB.")
        new_epub_path, metadata = result

        immutable_path, current_path = build_book_paths(new_epub_path.name, metadata["author"])
        new_epub_path.rename(immutable_path)
        shutil.copyfile(immutable_path, current_path)

        new_word_count, new_chapter_count = get_epub_word_and_chapter_count(current_path)
        update_data = schemas.BookUpdate(**metadata)
        updated_book = await crud.update_book(db=db, book=db_book, update_data=update_data)
        updated_book.removed_chapters = []
        updated_book.master_word_count = new_word_count
        updated_book.current_word_count = new_word_count
        updated_book.immutable_path = str(immutable_path.relative_to(LIBRARY_PATH.parent))
        updated_book.current_path = str(current_path.relative_to(LIBRARY_PATH.parent))
        updated_book.download_status = None
        await crud.touch_book_content(db, updated_book)
        await db.commit()
        await db.refresh(updated_book)

        log_entry = schemas.BookLogCreate(
            book_id=updated_book.id,
            entry_type="updated",
            previous_chapter_count=0,
            new_chapter_count=new_chapter_count,
            words_added=new_word_count,
        )
        await crud.create_book_log(db, log_entry)
        await epub_editor.apply_book_cleaning(updated_book, db)
        await queue_metadata_sync_job(db, trigger="book_update", book_ids=[updated_book.id])
        return updated_book

    immutable_path = LIBRARY_PATH.parent / db_book.immutable_path
    current_path = LIBRARY_PATH.parent / db_book.current_path

    old_word_count, old_chapter_count = get_epub_word_and_chapter_count(current_path)
    result = await download_web_novel(db_book.source_url, overwrite=True, existing_epub_path=immutable_path)
    if result is None:
        raise HTTPException(status_code=500, detail="FanFicFare did not update the existing EPUB during refresh.")
    new_epub_path, metadata = result

    if new_epub_path != immutable_path:
        new_epub_path.rename(immutable_path)
    shutil.copyfile(immutable_path, current_path)

    new_word_count, new_chapter_count = get_epub_word_and_chapter_count(current_path)

    if new_chapter_count > old_chapter_count:
        logger.info(f"Found {new_chapter_count - old_chapter_count} new chapters for {db_book.title}.")
        log_entry = schemas.BookLogCreate(
            book_id=db_book.id,
            entry_type="updated",
            previous_chapter_count=old_chapter_count,
            new_chapter_count=new_chapter_count,
            words_added=new_word_count - old_word_count,
        )
        await crud.create_book_log(db, log_entry)

    update_data = schemas.BookUpdate(**metadata)
    updated_book = await crud.update_book(db=db, book=db_book, update_data=update_data)

    # Reset per-source processing state; preserve per-book content_selectors
    updated_book.removed_chapters = []
    updated_book.master_word_count = new_word_count
    updated_book.current_word_count = new_word_count
    await crud.touch_book_content(db, updated_book)
    await db.commit()
    await db.refresh(updated_book)

    await epub_editor.apply_book_cleaning(updated_book, db)
    await queue_metadata_sync_job(db, trigger="book_update", book_ids=[updated_book.id])
    return updated_book


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
