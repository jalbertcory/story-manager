"""Cleaning configuration, preview, and durable processing endpoints."""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, epub_editor, models, schemas
from ..config import LIBRARY_PATH
from ..database import get_db
from ..services.processing_queue import get_processing_queue, queue_audio_reconciliation, queue_processing_job

logger = logging.getLogger(__name__)

router = APIRouter()


class PreviewCleaningRequest(BaseModel):
    content_selectors: List[str] = []
    removed_chapters: List[str] = []


async def _queue_clean_all(db: AsyncSession, detail: str):
    return await queue_processing_job(
        db=db,
        job_type="clean_all",
        payload={"reason": detail},
        dedupe_key="clean_all",
        progress_detail=detail,
    )


@router.post("/api/books/reprocess-all")
async def reprocess_all_books(response: Response, db: AsyncSession = Depends(get_db)):
    job = await _queue_clean_all(db, "Queued from Clean All Books")
    response.headers["X-Processing-Job-Id"] = str(job.id)
    return {"status": "started"}


@router.get("/api/books/reprocess-all/status")
async def reprocess_all_status(db: AsyncSession = Depends(get_db)):
    rows = await crud.get_processing_jobs(db, job_type="clean_all", limit=1)
    if not rows:
        return {"running": False}
    job, _title = rows[0]
    payload = {
        "running": job.status in ("queued", "running"),
        "job_id": job.id,
        "status": job.status,
        "total": job.progress_total,
        "processed": job.progress_current,
    }
    if job.error:
        payload["error"] = job.error
    return payload


@router.post("/api/books/{book_id}/process", response_model=schemas.Book)
async def process_book_endpoint(
    book_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    job = await queue_processing_job(
        db=db,
        job_type="clean_book",
        book_id=db_book.id,
        target_type="book",
        target_id=db_book.id,
        target_content_version=db_book.content_version,
        dedupe_key=f"clean_book:book:{db_book.id}",
        progress_detail="Queued from Clean Book",
    )
    response.headers["X-Processing-Job-Id"] = str(job.id)
    # Unit clients that do not enter the application lifespan have no workers.
    # Complete this ledger-backed job inline so service-level tests remain useful.
    if not get_processing_queue().is_running:
        changed = await epub_editor.apply_book_cleaning(db_book, db, force=True)
        if changed:
            await queue_audio_reconciliation(db_book, db, parent_job_id=job.id)
        await crud.complete_processing_job(
            db,
            job.id,
            "Cleaned book and queued derived audio" if changed else "Cleaning made no content changes",
        )
        await db.refresh(db_book)
    return db_book


@router.post("/api/books/{book_id}/preview-cleaning")
async def preview_cleaning(book_id: int, req: PreviewCleaningRequest, db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    configs = []
    if db_book.source_url:
        configs = await crud.get_all_matching_cleaning_configs(db, str(db_book.source_url))
    chapter_selectors, config_content_selectors = [], []
    for cfg in configs:
        chapter_selectors += list(cfg.chapter_selectors or [])
        config_content_selectors += list(cfg.content_selectors or [])
    all_content_selectors = config_content_selectors + req.content_selectors
    immutable_path = LIBRARY_PATH.parent / db_book.immutable_path
    return epub_editor.preview_epub(str(immutable_path), req.removed_chapters, all_content_selectors, chapter_selectors)


@router.get("/api/books/{book_id}/matched-config", response_model=List[schemas.CleaningConfig])
async def get_book_matched_config(book_id: int, db: AsyncSession = Depends(get_db)):
    """Returns all CleaningConfigs that match the book's source URL."""
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if not db_book.source_url:
        return []
    return await crud.get_all_matching_cleaning_configs(db, str(db_book.source_url))


@router.post("/api/cleaning-configs", status_code=status.HTTP_201_CREATED, response_model=schemas.CleaningConfig)
async def create_cleaning_config_endpoint(
    config: schemas.CleaningConfigCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> models.CleaningConfig:
    created = await crud.create_cleaning_config(db, config)
    job = await _queue_clean_all(db, f"Queued after creating cleaning config {created.name}")
    response.headers["X-Processing-Job-Id"] = str(job.id)
    return created


@router.get("/api/cleaning-configs", response_model=List[schemas.CleaningConfig])
async def list_cleaning_configs(db: AsyncSession = Depends(get_db)) -> List[models.CleaningConfig]:
    return await crud.get_cleaning_configs(db)


@router.get("/api/cleaning-configs/{config_id}", response_model=schemas.CleaningConfig)
async def get_cleaning_config_endpoint(config_id: int, db: AsyncSession = Depends(get_db)) -> models.CleaningConfig:
    config = await crud.get_cleaning_config(db, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Cleaning config not found")
    return config


@router.put("/api/cleaning-configs/{config_id}", response_model=schemas.CleaningConfig)
async def update_cleaning_config_endpoint(
    config_id: int,
    update: schemas.CleaningConfigUpdate,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> models.CleaningConfig:
    config = await crud.get_cleaning_config(db, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Cleaning config not found")
    config = await crud.update_cleaning_config(db, config, update)
    job = await _queue_clean_all(db, f"Queued after updating cleaning config {config.name}")
    response.headers["X-Processing-Job-Id"] = str(job.id)
    return config


@router.delete("/api/cleaning-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cleaning_config_endpoint(
    config_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> None:
    config = await crud.get_cleaning_config(db, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Cleaning config not found")
    name = config.name
    await crud.delete_cleaning_config(db, config)
    job = await _queue_clean_all(db, f"Queued after deleting cleaning config {name}")
    response.headers["X-Processing-Job-Id"] = str(job.id)
