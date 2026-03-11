"""Scheduler status, manual trigger, history, and per-task log endpoints."""

import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, schemas
from ..database import get_db
from ..services.web_novel import update_web_novels

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/scheduler/status", response_model=Optional[schemas.UpdateTask])
async def get_scheduler_status(db: AsyncSession = Depends(get_db)):
    return await crud.get_latest_update_task(db)


@router.post("/api/scheduler/trigger", status_code=202)
async def trigger_scheduler(background_tasks: BackgroundTasks):
    background_tasks.add_task(update_web_novels)
    return {"message": "Update triggered"}


@router.get("/api/scheduler/history", response_model=List[schemas.UpdateTask])
async def get_scheduler_history(limit: int = 20, offset: int = 0, db: AsyncSession = Depends(get_db)):
    return await crud.get_update_tasks(db, limit=limit, offset=offset)


@router.get("/api/scheduler/history/{task_id}/logs", response_model=List[schemas.BookLogWithTitle])
async def get_task_logs(task_id: int, db: AsyncSession = Depends(get_db)):
    task, rows = await crud.get_book_logs_for_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return [
        schemas.BookLogWithTitle(
            id=log.id,
            book_id=log.book_id,
            book_title=title,
            entry_type=log.entry_type,
            previous_chapter_count=log.previous_chapter_count,
            new_chapter_count=log.new_chapter_count,
            words_added=log.words_added,
            timestamp=log.timestamp,
        )
        for log, title in rows
    ]
