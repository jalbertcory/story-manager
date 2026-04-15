"""Book log and update task CRUD operations."""

from typing import List, Optional
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from .. import models, schemas


async def create_book_log(db: AsyncSession, log: schemas.BookLogCreate) -> models.BookLog:
    """Create a new book log entry in the database."""
    db_log = models.BookLog(**log.model_dump())
    db.add(db_log)
    await db.commit()
    await db.refresh(db_log)
    return db_log


async def get_latest_book_log(db: AsyncSession, book_id: int) -> Optional[models.BookLog]:
    result = await db.execute(
        select(models.BookLog).filter(models.BookLog.book_id == book_id).order_by(models.BookLog.timestamp.desc()).limit(1)
    )
    return result.scalars().first()


async def count_book_logs(db: AsyncSession, book_id: int) -> int:
    result = await db.execute(select(func.count(models.BookLog.id)).where(models.BookLog.book_id == book_id))
    return result.scalar() or 0


async def get_latest_update_task(db: AsyncSession) -> Optional[models.UpdateTask]:
    result = await db.execute(select(models.UpdateTask).order_by(models.UpdateTask.started_at.desc()).limit(1))
    return result.scalars().first()


async def get_active_update_task(db: AsyncSession) -> Optional[models.UpdateTask]:
    result = await db.execute(select(models.UpdateTask).filter(models.UpdateTask.status == "running"))
    return result.scalars().first()


async def create_update_task(db: AsyncSession, total_books: int) -> models.UpdateTask:
    task = models.UpdateTask(total_books=total_books, completed_books=0, status="running")
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def increment_update_task(db: AsyncSession, task: models.UpdateTask) -> None:
    task.completed_books += 1
    await db.commit()
    await db.refresh(task)


async def complete_update_task(db: AsyncSession, task: models.UpdateTask) -> None:
    task.status = "completed"
    task.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(task)


async def fail_update_task(db: AsyncSession, task: models.UpdateTask) -> None:
    task.status = "failed"
    task.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(task)


async def interrupt_update_task(db: AsyncSession, task: models.UpdateTask) -> None:
    task.status = "interrupted"
    task.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(task)


async def reset_stuck_update_tasks(db: AsyncSession) -> None:
    """Mark any tasks left in 'running' state (e.g. from a crashed run) as 'interrupted'."""
    result = await db.execute(select(models.UpdateTask).filter(models.UpdateTask.status == "running"))
    stuck = result.scalars().all()
    for task in stuck:
        task.status = "interrupted"
        task.completed_at = datetime.now(timezone.utc)
    if stuck:
        await db.commit()


async def get_update_tasks(db: AsyncSession, limit: int = 20, offset: int = 0) -> List[models.UpdateTask]:
    result = await db.execute(
        select(models.UpdateTask).order_by(models.UpdateTask.started_at.desc()).offset(offset).limit(limit)
    )
    return result.scalars().all()


async def get_book_logs_for_task(db: AsyncSession, task_id: int) -> tuple[Optional[models.UpdateTask], Optional[list]]:
    task_result = await db.execute(select(models.UpdateTask).filter(models.UpdateTask.id == task_id))
    task = task_result.scalars().first()
    if task is None:
        return None, None

    from datetime import timedelta

    start_filter = task.started_at - timedelta(seconds=1) if task.started_at else None
    conditions = [models.BookLog.timestamp >= start_filter] if start_filter is not None else []
    if task.completed_at:
        conditions.append(models.BookLog.timestamp <= task.completed_at)

    result = await db.execute(
        select(models.BookLog, models.Book.title)
        .join(models.Book, models.BookLog.book_id == models.Book.id)
        .filter(*conditions)
        .order_by(models.BookLog.timestamp.asc())
    )
    return task, result.all()
