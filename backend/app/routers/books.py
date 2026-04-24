"""Book CRUD, search, chapter listing, and download endpoints."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, epub_editor, models, schemas
from ..config import LIBRARY_PATH
from ..database import get_db
from ..services.catalog import build_book_catalog, normalize_genre_tags
from ..services.chapter_history import build_chapter_update_history
from ..services.library_paths import remove_empty_parent_dirs
from ..services.metadata_jobs import queue_metadata_sync_job

logger = logging.getLogger(__name__)

router = APIRouter()


def _remove_book_files(book: models.Book) -> list[str]:
    removed_paths: list[str] = []

    for relative_path in [book.immutable_path, book.current_path, book.cover_path]:
        if not relative_path:
            continue

        full_path = LIBRARY_PATH.parent / relative_path
        if full_path.exists():
            full_path.unlink()
            removed_paths.append(str(relative_path))
            remove_empty_parent_dirs(full_path)

    return removed_paths


def _book_cleanup_preview(book: models.Book) -> dict[str, Any]:
    files = []

    for relative_path in [book.immutable_path, book.current_path, book.cover_path]:
        if not relative_path:
            continue

        full_path = LIBRARY_PATH.parent / relative_path
        size_bytes = full_path.stat().st_size if full_path.exists() and full_path.is_file() else 0
        files.append({"path": relative_path, "size_bytes": size_bytes})

    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "files": files,
    }


@router.get("/api/books", response_model=List[schemas.Book])
async def get_all_books(
    skip: int = 0,
    limit: int = 100,
    sort_by: str = "title",
    sort_order: str = "asc",
    db: AsyncSession = Depends(get_db),
) -> List[schemas.Book]:
    books = await crud.get_books(db, skip=skip, limit=limit, sort_by=sort_by, sort_order=sort_order)
    return [schemas.Book.model_validate(book) for book in books]


@router.get("/api/books/catalog", response_model=List[schemas.BookCatalogEntry])
async def get_book_catalog(
    q: Optional[str] = None,
    sort_by: str = "title",
    sort_order: str = "asc",
    db: AsyncSession = Depends(get_db),
) -> List[schemas.BookCatalogEntry]:
    return await build_book_catalog(db, q=q, sort_by=sort_by, sort_order=sort_order)


@router.get("/api/series", response_model=List[str])
async def list_series(db: AsyncSession = Depends(get_db)) -> List[str]:
    """Return all distinct series names in the library, sorted alphabetically."""
    return await crud.get_all_series(db)


@router.put("/api/series/{series_name}")
async def rename_series(series_name: str, body: schemas.SeriesRename, db: AsyncSession = Depends(get_db)):
    """Rename a series, updating all books that belong to it."""
    new_name = body.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="New series name cannot be empty")
    count = await crud.rename_series(db, old_name=series_name, new_name=new_name)
    if count == 0:
        raise HTTPException(status_code=404, detail="No books found with that series name")
    return {"updated": count, "old_name": series_name, "new_name": new_name}


@router.post("/api/series/merge")
async def merge_series(body: schemas.SeriesMerge, db: AsyncSession = Depends(get_db)):
    """Merge source series into target series."""
    source = body.source.strip()
    target = body.target.strip()
    if not source or not target:
        raise HTTPException(status_code=400, detail="Source and target series names are required")
    if source.lower() == target.lower():
        raise HTTPException(status_code=400, detail="Source and target series must be different")
    count = await crud.merge_series(db, source=source, target=target)
    if count == 0:
        raise HTTPException(status_code=404, detail="No books found in source series")
    return {"merged": count, "source": source, "target": target}


@router.post("/api/series/{series_name}/reorder")
async def reorder_series(series_name: str, body: schemas.SeriesReorder, db: AsyncSession = Depends(get_db)):
    """Persist the order of every book in a series."""
    count = await crud.reorder_series_books(db, series=series_name, ordered_book_ids=body.ordered_book_ids)
    if count == 0:
        raise HTTPException(status_code=404, detail="No books found with that series name")
    return {"updated": count, "series": series_name}


@router.get("/api/series/{series_name}/genres", response_model=schemas.SeriesMetadataSummary)
async def get_series_genres(
    series_name: str,
    db: AsyncSession = Depends(get_db),
):
    books = await crud.get_books_by_series(db, series=series_name, skip=0, limit=1)
    if not books:
        raise HTTPException(status_code=404, detail="No books found with that series name")

    canonical_name = books[0].series or series_name
    metadata = await crud.get_series_metadata(db, canonical_name)
    return schemas.SeriesMetadataSummary(
        series_name=canonical_name,
        user_genre_tags=list(metadata.user_genre_tags or []) if metadata else [],
    )


@router.put("/api/series/{series_name}/genres", response_model=schemas.SeriesMetadataSummary)
async def update_series_genres(
    series_name: str,
    body: schemas.SeriesGenresUpdate,
    db: AsyncSession = Depends(get_db),
):
    books = await crud.get_books_by_series(db, series=series_name, skip=0, limit=1)
    if not books:
        raise HTTPException(status_code=404, detail="No books found with that series name")

    crud.validate_genre_tags(body.user_genre_tags)
    canonical_name = books[0].series or series_name
    user_genre_tags = normalize_genre_tags(body.user_genre_tags)
    metadata = await crud.set_series_user_genre_tags(
        db,
        series_name=canonical_name,
        user_genre_tags=user_genre_tags,
    )
    return schemas.SeriesMetadataSummary(
        series_name=canonical_name,
        user_genre_tags=list(metadata.user_genre_tags or []) if metadata else [],
    )


@router.get("/api/books/search", response_model=List[schemas.Book])
async def search_books_unified(
    q: str,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> List[schemas.Book]:
    return await crud.search_books(db, q=q, skip=skip, limit=limit)


@router.get("/api/books/search/author/{author}", response_model=List[schemas.Book])
async def search_books_by_author(
    author: str, skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)
) -> List[models.Book]:
    return await crud.get_books_by_author(db, author=author, skip=skip, limit=limit)


@router.get("/api/books/search/series/{series}", response_model=List[schemas.Book])
async def search_books_by_series(
    series: str, skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)
) -> List[models.Book]:
    return await crud.get_books_by_series(db, series=series, skip=skip, limit=limit)


@router.get("/api/books/count")
async def count_books_endpoint(q: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    total = await crud.count_books(db, q=q)
    return {"total": total}


@router.get("/api/books/details", response_model=List[schemas.Book])
async def get_book_details(book_ids: List[int] = Query(alias="ids"), db: AsyncSession = Depends(get_db)) -> List[schemas.Book]:
    books = await crud.get_books_by_ids(db, book_ids=book_ids)
    return [schemas.Book.model_validate(book) for book in books]


@router.get("/api/books/{book_id}/update-history", response_model=schemas.BookChapterUpdateHistory)
async def get_book_update_history(book_id: int, db: AsyncSession = Depends(get_db)) -> schemas.BookChapterUpdateHistory:
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    logs = await crud.get_book_logs(db, book_id)
    return build_chapter_update_history(book_id, logs)


@router.get("/api/books/{book_id}", response_model=schemas.Book)
async def get_book(book_id: int, db: AsyncSession = Depends(get_db)) -> models.Book:
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return db_book


@router.put("/api/books/{book_id}", response_model=schemas.Book)
async def update_book_details(
    book_id: int, book_update: schemas.BookUpdate, db: AsyncSession = Depends(get_db)
) -> models.Book:
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    previous_title = db_book.title
    previous_author = db_book.author
    previous_series = db_book.series
    previous_remote_ids = db_book.metadata_remote_ids
    if book_update.user_genre_tags is not None:
        book_update.user_genre_tags = normalize_genre_tags(book_update.user_genre_tags)
    update_dict = book_update.model_dump(exclude_unset=True)
    updated_book = await crud.update_book(db=db, book=db_book, update_data=book_update)
    if "content_selectors" in update_dict or "removed_chapters" in update_dict:
        await epub_editor.apply_book_cleaning(updated_book, db)
    if (
        updated_book.title != previous_title
        or updated_book.author != previous_author
        or updated_book.series != previous_series
        or updated_book.metadata_remote_ids != previous_remote_ids
    ):
        await queue_metadata_sync_job(db, trigger="book_update", book_ids=[updated_book.id])
    if updated_book.series != previous_series:
        await crud.cleanup_orphaned_series_metadata(db)
    return updated_book


@router.get("/api/books/{book_id}/chapters", response_model=List[Dict[str, Any]])
async def get_book_chapters(book_id: int, db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if not db_book.immutable_path:
        raise HTTPException(status_code=404, detail="EPUB file not found")

    epub_path = LIBRARY_PATH.parent / db_book.immutable_path
    if not epub_path.exists():
        raise HTTPException(status_code=404, detail="EPUB file not found")

    return epub_editor.get_chapters(str(epub_path))


@router.get("/api/books/{book_id}/cleaned-chapters", response_model=List[Dict[str, Any]])
async def get_book_cleaned_chapters(book_id: int, db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if not db_book.current_path:
        raise HTTPException(status_code=404, detail="Cleaned EPUB file not found")

    epub_path = LIBRARY_PATH.parent / db_book.current_path
    if not epub_path.exists():
        raise HTTPException(status_code=404, detail="Cleaned EPUB file not found")

    return epub_editor.get_chapters(str(epub_path))


@router.get("/api/books/{book_id}/download")
async def download_book(book_id: int, db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    current_path = LIBRARY_PATH.parent / db_book.current_path
    if not current_path.is_file():
        raise HTTPException(status_code=404, detail="EPUB file not found")
    filename = Path(db_book.current_path).name
    return FileResponse(
        current_path,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/books/remove-all")
async def remove_all_books(dry_run: bool = True, db: AsyncSession = Depends(get_db)):
    books = await crud.get_books(db, limit=100000)

    preview_books = []
    total_files = 0
    total_bytes = 0
    total_logs = 0
    all_paths: list[str] = []

    for book in books:
        book_preview = _book_cleanup_preview(book)
        book_log_count = await crud.count_book_logs(db, book.id)
        preview_books.append(
            {
                **book_preview,
                "log_entries": book_log_count,
            }
        )
        total_logs += book_log_count
        total_files += len(book_preview["files"])
        total_bytes += sum(file["size_bytes"] for file in book_preview["files"])
        all_paths.extend(file["path"] for file in book_preview["files"])

    if not dry_run:
        for book in books:
            _remove_book_files(book)
        deleted_books = await crud.delete_all_books(db)
        logger.warning("Removed %s books from the library.", deleted_books)

    return {
        "dry_run": dry_run,
        "book_count": len(books),
        "file_count": total_files,
        "total_bytes": total_bytes,
        "log_count": total_logs,
        "books": preview_books,
        "paths": all_paths,
    }


@router.delete("/api/books/by-title/{title}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book_by_title(title: str, db: AsyncSession = Depends(get_db)):
    book = await crud.get_book_by_title(db, title=title)
    if book is None:
        return None

    _remove_book_files(book)
    await crud.delete_book(db, book=book)
    await crud.cleanup_orphaned_series_metadata(db)
    return None


@router.delete("/api/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book_by_id(book_id: int, db: AsyncSession = Depends(get_db)):
    book = await crud.get_book(db, book_id=book_id)
    if book is None:
        return None

    _remove_book_files(book)
    await crud.delete_book(db, book=book)
    await crud.cleanup_orphaned_series_metadata(db)
    return None
