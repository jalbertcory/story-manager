"""Cover image endpoints: serve, upload, and set from URL."""

from .. import api_schemas as contracts
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..config import LIBRARY_PATH
from ..database import get_db
from ..services.cover_images import save_cover_from_url
from ..services.processing_queue import queue_processing_job
from ..upload_validation import MAX_IMAGE_BYTES, detect_image_extension, read_upload_limited, validate_image_upload

logger = logging.getLogger(__name__)

router = APIRouter()


class CoverUrlRequest(BaseModel):
    url: str


@router.get(
    "/api/covers/{book_id}", response_model=None, response_class=Response, responses=contracts.media_responses("image/*")
)
async def get_cover_image(book_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    """Serves the cover image for a given book ID."""
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None or not db_book.cover_path:
        raise HTTPException(status_code=404, detail="Cover not found")

    cover_path = LIBRARY_PATH.parent / db_book.cover_path
    if not cover_path.is_file():
        raise HTTPException(status_code=404, detail="Cover file not found")

    return FileResponse(
        cover_path,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post("/api/books/{book_id}/cover", response_model=schemas.Book)
async def upload_book_cover(book_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)) -> models.Book:
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    payload = await read_upload_limited(file, MAX_IMAGE_BYTES, file.filename or "cover")
    validate_image_upload(payload, file.filename or "cover")

    covers_path = (LIBRARY_PATH / "covers").resolve()
    covers_path.mkdir(exist_ok=True)
    ext = detect_image_extension(payload)
    if ext is None:  # validate_image_upload already guards this path
        raise HTTPException(status_code=400, detail="Unsupported cover image format")
    save_path = covers_path / f"{book_id}{ext}"
    with open(save_path, "wb") as f:
        f.write(payload)

    db_book.cover_path = str(save_path.relative_to(LIBRARY_PATH.parent))
    await db.commit()
    await db.refresh(db_book)
    return db_book


@router.post("/api/books/{book_id}/retry-cover", response_model=schemas.Book)
async def retry_cover(book_id: int, response: Response, db: AsyncSession = Depends(get_db)) -> models.Book:
    """Queue cover extraction from the EPUB with source scraping as fallback."""
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if not db_book.immutable_path:
        raise HTTPException(status_code=400, detail="Book has no EPUB file to extract cover from")

    job = await queue_processing_job(
        db=db,
        job_type="retry_cover",
        book_id=db_book.id,
        target_type="book",
        target_id=db_book.id,
        dedupe_key=f"retry_cover:book:{db_book.id}",
        progress_detail="Queued from Re-extract Cover",
    )
    response.headers["X-Processing-Job-Id"] = str(job.id)
    return db_book


@router.post("/api/books/{book_id}/cover-url", response_model=schemas.Book)
async def set_cover_from_url(book_id: int, req: CoverUrlRequest, db: AsyncSession = Depends(get_db)) -> models.Book:
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
