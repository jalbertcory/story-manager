"""Scheduler orchestration for recurring web novel update runs."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .. import crud, models
from ..database import SessionLocal
from .metadata_jobs import queue_stale_metadata_sync
from .web_novel import update_web_novels

logger = logging.getLogger(__name__)

WEB_NOVEL_UPDATE_JOB_ID = "update_web_novels"
WEB_NOVEL_UPDATE_INTERVAL_HOURS = 24
WEB_NOVEL_UPDATE_INTERVAL = timedelta(hours=WEB_NOVEL_UPDATE_INTERVAL_HOURS)
METADATA_STALE_SCAN_JOB_ID = "enqueue_stale_metadata_sync"
METADATA_STALE_SCAN_INTERVAL_HOURS = 24
METADATA_STALE_SCAN_INTERVAL = timedelta(hours=METADATA_STALE_SCAN_INTERVAL_HOURS)
METADATA_SYNC_STALE_AFTER_DAYS = 30
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


def get_metadata_schedule_label() -> str:
    return f"Check for stale metadata every {METADATA_STALE_SCAN_INTERVAL_HOURS} hours"


def get_scheduled_job():
    return _scheduler.get_job(WEB_NOVEL_UPDATE_JOB_ID)


def get_metadata_scheduled_job():
    return _scheduler.get_job(METADATA_STALE_SCAN_JOB_ID)


def is_update_running() -> bool:
    return _run_lock.locked()


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def has_daily_schedule(settings: Optional[models.SchedulerSettings]) -> bool:
    return bool(
        settings is not None
        and settings.web_novel_schedule_hour is not None
        and settings.web_novel_schedule_minute is not None
        and settings.web_novel_schedule_timezone
    )


def get_schedule_mode(settings: Optional[models.SchedulerSettings]) -> str:
    return "daily_time" if has_daily_schedule(settings) else "interval"


def get_schedule_time_local(settings: Optional[models.SchedulerSettings]) -> Optional[str]:
    if not has_daily_schedule(settings):
        return None
    return f"{settings.web_novel_schedule_hour:02d}:{settings.web_novel_schedule_minute:02d}"


def get_schedule_timezone(settings: Optional[models.SchedulerSettings]) -> Optional[str]:
    if not has_daily_schedule(settings):
        return None
    return settings.web_novel_schedule_timezone


def _format_hour_minute(hour: int, minute: int) -> str:
    suffix = "AM" if hour < 12 else "PM"
    hour_12 = hour % 12 or 12
    return f"{hour_12}:{minute:02d} {suffix}"


def get_schedule_label(settings: Optional[models.SchedulerSettings] = None) -> str:
    if has_daily_schedule(settings):
        return (
            f"Daily at {_format_hour_minute(settings.web_novel_schedule_hour, settings.web_novel_schedule_minute)} "
            f"({settings.web_novel_schedule_timezone})"
        )
    return f"Every {WEB_NOVEL_UPDATE_INTERVAL_HOURS} hours"


def _get_zoneinfo(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown scheduler timezone %s; falling back to UTC.", timezone_name)
        return ZoneInfo("UTC")


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


def calculate_next_daily_run_time(
    hour: int,
    minute: int,
    timezone_name: str,
    now: Optional[datetime] = None,
) -> datetime:
    now_utc = _as_utc(now) or datetime.now(timezone.utc)
    schedule_tz = _get_zoneinfo(timezone_name)
    now_local = now_utc.astimezone(schedule_tz)
    next_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_local <= now_local:
        next_local += timedelta(days=1)
    return next_local.astimezone(timezone.utc)


def get_next_run_time_for_task(
    task: Optional[models.UpdateTask],
    schedule_settings: Optional[models.SchedulerSettings] = None,
    now: Optional[datetime] = None,
) -> datetime:
    now_utc = _as_utc(now) or datetime.now(timezone.utc)
    if task is not None and task.status == "interrupted" and task.completed_books < task.total_books:
        return now_utc + OVERDUE_RUN_DELAY
    if has_daily_schedule(schedule_settings):
        return calculate_next_daily_run_time(
            schedule_settings.web_novel_schedule_hour,
            schedule_settings.web_novel_schedule_minute,
            schedule_settings.web_novel_schedule_timezone,
            now=now_utc,
        )
    return calculate_next_run_time(get_last_run_anchor(task), now=now_utc)


async def schedule_next_web_novel_update() -> datetime:
    async with SessionLocal() as db:
        latest_task = await crud.get_latest_update_task(db)
        schedule_settings = await crud.get_scheduler_settings(db)

    next_run_at = get_next_run_time_for_task(latest_task, schedule_settings=schedule_settings)
    _scheduler.add_job(
        run_web_novel_update,
        "date",
        id=WEB_NOVEL_UPDATE_JOB_ID,
        replace_existing=True,
        run_date=next_run_at,
    )
    logger.info("Next web novel update scheduled for %s.", next_run_at.isoformat())
    return next_run_at


async def schedule_next_metadata_recheck(now: Optional[datetime] = None) -> datetime:
    next_run_at = (_as_utc(now) or datetime.now(timezone.utc)) + METADATA_STALE_SCAN_INTERVAL
    _scheduler.add_job(
        run_metadata_recheck,
        "date",
        id=METADATA_STALE_SCAN_JOB_ID,
        replace_existing=True,
        run_date=next_run_at,
    )
    logger.info("Next metadata stale-check scheduled for %s.", next_run_at.isoformat())
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


async def run_metadata_recheck(trigger: str = "scheduled") -> bool:
    logger.info("Starting %s metadata stale-check.", trigger)
    try:
        async with SessionLocal() as db:
            job = await queue_stale_metadata_sync(db, stale_after_days=METADATA_SYNC_STALE_AFTER_DAYS)
        return job is not None
    finally:
        await schedule_next_metadata_recheck()
