"""Book CRUD, search, chapter listing, and download endpoints."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, epub_editor, models, schemas
from ..config import LIBRARY_PATH
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/books", response_model=List[schemas.Book])
async def get_all_books(
    skip: int = 0,
    limit: int = 100,
    sort_by: str = "title",
    sort_order: str = "asc",
    db: AsyncSession = Depends(get_db),
) -> List[schemas.Book]:
    books = await crud.get_books(db, skip=skip, limit=limit, sort_by=sort_by, sort_order=sort_order)
    return [schemas.Book.from_orm(book) for book in books]


@router.get("/api/series", response_model=List[str])
async def list_series(db: AsyncSession = Depends(get_db)) -> List[str]:
    """Return all distinct series names in the library, sorted alphabetically."""
    return await crud.get_all_series(db)


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
    update_dict = book_update.model_dump(exclude_unset=True)
    updated_book = await crud.update_book(db=db, book=db_book, update_data=book_update)
    if "content_selectors" in update_dict or "removed_chapters" in update_dict:
        await epub_editor.apply_book_cleaning(updated_book, db)
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


@router.get("/api/books/{book_id}/download")
async def download_book(book_id: int, db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    from pathlib import Path

    current_path = LIBRARY_PATH.parent / db_book.current_path
    if not current_path.is_file():
        raise HTTPException(status_code=404, detail="EPUB file not found")
    filename = Path(db_book.current_path).name
    return FileResponse(
        current_path,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/api/books/by-title/{title}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book_by_title(title: str, db: AsyncSession = Depends(get_db)):
    book = await crud.get_book_by_title(db, title=title)
    if book is None:
        return None

    if book.immutable_path:
        p = LIBRARY_PATH.parent / book.immutable_path
        if p.exists():
            p.unlink()
    if book.current_path:
        p = LIBRARY_PATH.parent / book.current_path
        if p.exists():
            p.unlink()

    await crud.delete_book(db, book=book)
    return None


@router.delete("/api/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book_by_id(book_id: int, db: AsyncSession = Depends(get_db)):
    book = await crud.get_book(db, book_id=book_id)
    if book is None:
        return None

    if book.immutable_path:
        p = LIBRARY_PATH.parent / book.immutable_path
        if p.exists():
            p.unlink()
    if book.current_path:
        p = LIBRARY_PATH.parent / book.current_path
        if p.exists():
            p.unlink()

    await crud.delete_book(db, book=book)
    return None
