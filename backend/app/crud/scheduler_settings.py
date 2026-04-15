"""Scheduler settings CRUD operations."""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .. import models


async def get_scheduler_settings(db: AsyncSession) -> Optional[models.SchedulerSettings]:
    result = await db.execute(select(models.SchedulerSettings).order_by(models.SchedulerSettings.id.asc()).limit(1))
    return result.scalars().first()


async def upsert_scheduler_settings(
    db: AsyncSession,
    *,
    web_novel_schedule_hour: int,
    web_novel_schedule_minute: int,
    web_novel_schedule_timezone: str,
) -> models.SchedulerSettings:
    settings = await get_scheduler_settings(db)
    if settings is None:
        settings = models.SchedulerSettings(
            web_novel_schedule_hour=web_novel_schedule_hour,
            web_novel_schedule_minute=web_novel_schedule_minute,
            web_novel_schedule_timezone=web_novel_schedule_timezone,
        )
        db.add(settings)
    else:
        settings.web_novel_schedule_hour = web_novel_schedule_hour
        settings.web_novel_schedule_minute = web_novel_schedule_minute
        settings.web_novel_schedule_timezone = web_novel_schedule_timezone

    await db.commit()
    await db.refresh(settings)
    return settings
