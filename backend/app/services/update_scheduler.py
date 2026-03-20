"""Scheduler orchestration for recurring web novel update runs."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .. import crud, models
from ..database import SessionLocal
from .web_novel import update_web_novels

logger = logging.getLogger(__name__)

WEB_NOVEL_UPDATE_JOB_ID = "update_web_novels"
WEB_NOVEL_UPDATE_INTERVAL_HOURS = 24
WEB_NOVEL_UPDATE_INTERVAL = timedelta(hours=WEB_NOVEL_UPDATE_INTERVAL_HOURS)
OVERDUE_RUN_DELAY = timedelta(seconds=5)

_run_lock = asyncio.Lock()
_scheduler = AsyncIOScheduler(
    job_defaults={
        "coalesce": True,
        "max_instances": 1,
    },
    timezone=timezone.utc,
)


def get_scheduler() -> AsyncIOScheduler:
    return _scheduler


def is_scheduler_running() -> bool:
    return _scheduler.running


def get_schedule_label() -> str:
    return f"Every {WEB_NOVEL_UPDATE_INTERVAL_HOURS} hours"


def get_scheduled_job():
    return _scheduler.get_job(WEB_NOVEL_UPDATE_JOB_ID)


def is_update_running() -> bool:
    return _run_lock.locked()


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_last_run_anchor(task: Optional[models.UpdateTask]) -> Optional[datetime]:
    if task is None:
        return None
    if task.status == "completed" and task.completed_at is not None:
        return _as_utc(task.completed_at)
    return _as_utc(task.started_at or task.completed_at)


def calculate_next_run_time(last_run_at: Optional[datetime], now: Optional[datetime] = None) -> datetime:
    now_utc = _as_utc(now) or datetime.now(timezone.utc)
    last_run_utc = _as_utc(last_run_at)
    if last_run_utc is None:
        return now_utc + WEB_NOVEL_UPDATE_INTERVAL

    next_run_at = last_run_utc + WEB_NOVEL_UPDATE_INTERVAL
    if next_run_at <= now_utc:
        return now_utc + OVERDUE_RUN_DELAY
    return next_run_at


async def schedule_next_web_novel_update() -> datetime:
    async with SessionLocal() as db:
        latest_task = await crud.get_latest_update_task(db)

    next_run_at = calculate_next_run_time(get_last_run_anchor(latest_task))
    _scheduler.add_job(
        run_web_novel_update,
        "date",
        id=WEB_NOVEL_UPDATE_JOB_ID,
        replace_existing=True,
        run_date=next_run_at,
    )
    logger.info("Next web novel update scheduled for %s.", next_run_at.isoformat())
    return next_run_at


async def run_web_novel_update(trigger: str = "scheduled") -> bool:
    if _run_lock.locked():
        logger.info("Skipping %s web novel update because another run is already in progress.", trigger)
        return False

    async with _run_lock:
        logger.info("Starting %s web novel update.", trigger)
        try:
            await update_web_novels()
            return True
        finally:
            await schedule_next_web_novel_update()
