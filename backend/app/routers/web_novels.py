"""Web novel endpoints: add from URL and refresh from source."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, epub_editor, models, schemas
from ..config import LIBRARY_PATH
from ..database import get_db
from ..services.epub_utils import get_epub_word_and_chapter_count
from ..services.web_novel import download_web_novel, finish_web_novel_download

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
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> models.Book:
    """Creates a pending book record immediately and downloads the web novel in the background."""
    source_url_str = str(request.url)

    existing_book = await crud.get_book_by_source_url(db, source_url=source_url_str)
    if existing_book:
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
    background_tasks.add_task(finish_web_novel_download, db_book.id, source_url_str)
    return db_book


@router.post("/api/books/{book_id}/refresh", response_model=schemas.Book)
async def refresh_book(book_id: int, db: AsyncSession = Depends(get_db)) -> models.Book:
    """Re-downloads a web novel from its source URL and applies cleaning."""
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if not db_book.source_url:
        raise HTTPException(status_code=400, detail="Book does not have a source URL to refresh from.")

    immutable_path = LIBRARY_PATH.parent / db_book.immutable_path
    current_path = LIBRARY_PATH.parent / db_book.current_path

    old_word_count, old_chapter_count = get_epub_word_and_chapter_count(current_path)
    new_epub_path, metadata = await download_web_novel(db_book.source_url, overwrite=True)

    new_epub_path.rename(immutable_path)
    with open(immutable_path, "rb") as f_in, open(current_path, "wb") as f_out:
        f_out.write(f_in.read())

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
    return updated_book
