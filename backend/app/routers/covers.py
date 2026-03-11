"""Cover image endpoints: serve, upload, and set from URL."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, schemas
from ..config import LIBRARY_PATH
from ..database import get_db
from ..services.web_novel import save_cover_from_url

logger = logging.getLogger(__name__)

router = APIRouter()


class CoverUrlRequest(BaseModel):
    url: str


@router.get("/api/covers/{book_id}")
async def get_cover_image(book_id: int, db: AsyncSession = Depends(get_db)):
    """Serves the cover image for a given book ID."""
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None or not db_book.cover_path:
        raise HTTPException(status_code=404, detail="Cover not found")

    cover_path = LIBRARY_PATH.parent / db_book.cover_path
    if not cover_path.is_file():
        raise HTTPException(status_code=404, detail="Cover file not found")

    return FileResponse(cover_path)


@router.post("/api/books/{book_id}/cover", response_model=schemas.Book)
async def upload_book_cover(book_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    covers_path = (LIBRARY_PATH / "covers").resolve()
    covers_path.mkdir(exist_ok=True)
    ext = Path(file.filename).suffix or ".jpg"
    save_path = covers_path / f"{book_id}{ext}"
    with open(save_path, "wb") as f:
        f.write(await file.read())

    db_book.cover_path = str(save_path.relative_to(LIBRARY_PATH.parent))
    await db.commit()
    await db.refresh(db_book)
    return db_book


@router.post("/api/books/{book_id}/cover-url", response_model=schemas.Book)
async def set_cover_from_url(book_id: int, req: CoverUrlRequest, db: AsyncSession = Depends(get_db)):
    """Downloads an image from a URL and sets it as the book's cover."""
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    save_path = await save_cover_from_url(req.url, book_id)
    if save_path is None:
        raise HTTPException(status_code=400, detail="Failed to download image from the provided URL")

    db_book.cover_path = str(save_path.relative_to(LIBRARY_PATH.parent))
    await db.commit()
    await db.refresh(db_book)
    return db_book
