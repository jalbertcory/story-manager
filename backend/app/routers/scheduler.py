"""Scheduler status, manual trigger, history, and per-task log endpoints."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from apscheduler.job import Job
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..database import get_db
from ..services import update_scheduler
from ..services.processing_queue import queue_processing_job

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_scheduler_job_status(
    latest_task: Optional[models.UpdateTask],
    schedule_settings: models.SchedulerSettings | None,
    job: Job | None,
) -> schemas.SchedulerJobStatus:
    next_run_at = job.next_run_time if job is not None else None
    return schemas.SchedulerJobStatus(
        job_id=update_scheduler.WEB_NOVEL_UPDATE_JOB_ID,
        schedule=update_scheduler.get_schedule_label(schedule_settings),
        schedule_mode=update_scheduler.get_schedule_mode(schedule_settings),
        schedule_time_local=update_scheduler.get_schedule_time_local(schedule_settings),
        schedule_timezone=update_scheduler.get_schedule_timezone(schedule_settings),
        next_run_at=next_run_at,
        scheduler_running=update_scheduler.is_scheduler_running(),
        run_in_progress=update_scheduler.is_update_running(),
        last_run_started_at=latest_task.started_at if latest_task is not None else None,
        last_run_completed_at=latest_task.completed_at if latest_task is not None else None,
        last_run_status=latest_task.status if latest_task is not None else None,
    )


@router.get("/api/scheduler/status", response_model=Optional[schemas.UpdateTask])
async def get_scheduler_status(db: AsyncSession = Depends(get_db)) -> models.UpdateTask | None:
    return await crud.get_latest_update_task(db)


@router.get("/api/scheduler/job", response_model=schemas.SchedulerJobStatus)
async def get_scheduler_job_status(db: AsyncSession = Depends(get_db)) -> schemas.SchedulerJobStatus:
    latest_task = await crud.get_latest_update_task(db)
    schedule_settings = await crud.get_scheduler_settings(db)
    job = update_scheduler.get_scheduled_job()
    return _build_scheduler_job_status(latest_task, schedule_settings, job)


@router.put("/api/scheduler/config", response_model=schemas.SchedulerJobStatus)
async def update_scheduler_config(
    config: schemas.SchedulerConfigUpdate, db: AsyncSession = Depends(get_db)
) -> schemas.SchedulerJobStatus:
    hour_text, minute_text = config.time_local.split(":")
    schedule_settings = await crud.upsert_scheduler_settings(
        db,
        web_novel_schedule_hour=int(hour_text),
        web_novel_schedule_minute=int(minute_text),
        web_novel_schedule_timezone=config.timezone,
    )
    await update_scheduler.schedule_next_web_novel_update()
    latest_task = await crud.get_latest_update_task(db)
    job = update_scheduler.get_scheduled_job()
    return _build_scheduler_job_status(latest_task, schedule_settings, job)


@router.post("/api/scheduler/trigger", status_code=202, response_model=None)
async def trigger_scheduler(db: AsyncSession = Depends(get_db)) -> dict[str, str | int]:
    job = await queue_processing_job(
        db=db,
        job_type="refresh_all",
        payload={"trigger": "manual"},
        dedupe_key="refresh_all",
        progress_detail="Queued from Run Now",
    )
    return {"message": "Update queued", "processing_job_id": job.id}


@router.get("/api/scheduler/history", response_model=List[schemas.UpdateTask])
async def get_scheduler_history(
    limit: int = 20, offset: int = 0, db: AsyncSession = Depends(get_db)
) -> list[models.UpdateTask]:
    return await crud.get_update_tasks(db, limit=limit, offset=offset)


@router.get("/api/scheduler/history/{task_id}/logs", response_model=List[schemas.BookLogWithTitle])
async def get_task_logs(task_id: int, db: AsyncSession = Depends(get_db)) -> list[schemas.BookLogWithTitle]:
    task, rows = await crud.get_book_logs_for_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    assert rows is not None
    results = []
    for log, title in rows:
        assert log.timestamp is not None  # Persisted logs receive the database timestamp default.
        results.append(
            schemas.BookLogWithTitle(
                id=log.id,
                book_id=log.book_id,
                book_title=title or "",
                entry_type=log.entry_type,
                previous_chapter_count=log.previous_chapter_count,
                new_chapter_count=log.new_chapter_count,
                words_added=log.words_added,
                timestamp=log.timestamp,
            )
        )
    return results
