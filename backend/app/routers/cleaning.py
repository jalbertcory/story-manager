"""Cleaning config CRUD, per-book processing, and cleaning preview endpoints."""

import asyncio
import logging
import re
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, epub_editor, models, schemas
from ..config import LIBRARY_PATH
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

_reprocess_lock = asyncio.Lock()
_reprocess_status: dict | None = None


class PreviewCleaningRequest(BaseModel):
    content_selectors: List[str] = []
    removed_chapters: List[str] = []


async def _run_reprocess_all(db: AsyncSession):
    global _reprocess_status
    try:
        books = await crud.get_books(db, limit=10000)
        configs = await crud.get_cleaning_configs(db)
        total = len(books)
        updated = 0
        for i, book in enumerate(books):
            _reprocess_status = {"running": True, "total": total, "processed": i, "updated": updated}
            changed = await epub_editor.apply_book_cleaning(book, db, force=True, cleaning_configs=configs)
            if changed:
                updated += 1
        _reprocess_status = {"running": False, "total": total, "processed": total, "updated": updated}
        logger.info("Reprocess-all complete: %d/%d books updated.", updated, total)
    except Exception:
        logger.error("Reprocess-all failed", exc_info=True)
        _reprocess_status = {"running": False, "error": "Reprocess failed, check logs."}
    finally:
        _reprocess_lock.release()


@router.post("/api/books/reprocess-all")
async def reprocess_all_books(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    if not await _start_reprocess(background_tasks, db):
        raise HTTPException(status_code=409, detail="Reprocess already in progress")
    return {"status": "started"}


@router.get("/api/books/reprocess-all/status")
async def reprocess_all_status():
    if _reprocess_status is None:
        return {"running": False}
    return _reprocess_status


@router.post("/api/books/{book_id}/process", response_model=schemas.Book)
async def process_book_endpoint(book_id: int, db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    await epub_editor.apply_book_cleaning(db_book, db, force=True)
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
    config: schemas.CleaningConfigCreate, db: AsyncSession = Depends(get_db)
) -> models.CleaningConfig:
    return await crud.create_cleaning_config(db, config)


@router.get("/api/cleaning-configs", response_model=List[schemas.CleaningConfig])
async def list_cleaning_configs(db: AsyncSession = Depends(get_db)) -> List[models.CleaningConfig]:
    return await crud.get_cleaning_configs(db)


@router.get("/api/cleaning-configs/{config_id}", response_model=schemas.CleaningConfig)
async def get_cleaning_config_endpoint(config_id: int, db: AsyncSession = Depends(get_db)) -> models.CleaningConfig:
    config = await crud.get_cleaning_config(db, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Cleaning config not found")
    return config


async def _start_reprocess(background_tasks: BackgroundTasks, db: AsyncSession):
    """Start a reprocess-all run if one isn't already running."""
    if _reprocess_lock.locked():
        return False
    await _reprocess_lock.acquire()
    background_tasks.add_task(_run_reprocess_all, db)
    return True


@router.put("/api/cleaning-configs/{config_id}", response_model=schemas.CleaningConfig)
async def update_cleaning_config_endpoint(
    config_id: int,
    update: schemas.CleaningConfigUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> models.CleaningConfig:
    config = await crud.get_cleaning_config(db, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Cleaning config not found")
    config = await crud.update_cleaning_config(db, config, update)
    await _start_reprocess(background_tasks, db)
    return config


@router.delete("/api/cleaning-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cleaning_config_endpoint(config_id: int, db: AsyncSession = Depends(get_db)) -> None:
    config = await crud.get_cleaning_config(db, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Cleaning config not found")
    await crud.delete_cleaning_config(db, config)
    return None
