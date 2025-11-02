from typing import List, Optional
from datetime import datetime
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from . import models, schemas


async def get_book_by_source_url(db: AsyncSession, source_url: str) -> Optional[models.Book]:
    """
    Retrieve a single book from the database by its source URL.
    """
    result = await db.execute(select(models.Book).filter(models.Book.source_url == source_url))
    return result.scalars().first()


async def get_web_books(db: AsyncSession) -> List[models.Book]:
    """
    Retrieve all web books from the database.
    """
    result = await db.execute(select(models.Book).filter(models.Book.source_type == models.SourceType.web))
    return result.scalars().all()


async def get_books(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[models.Book]:
    """
    Retrieve a list of books from the database.
    """
    result = await db.execute(select(models.Book).offset(skip).limit(limit))
    return result.scalars().all()


async def create_book(db: AsyncSession, book: schemas.BookCreate) -> models.Book:
    """
    Create a new book record in the database.
    """
    book_data = book.model_dump(exclude_unset=True)
    if "source_url" in book_data and book_data["source_url"] is not None:
        book_data["source_url"] = str(book_data["source_url"])

    db_book = models.Book(**book_data)
    db.add(db_book)
    await db.commit()
    await db.refresh(db_book)
    return db_book


async def get_book(db: AsyncSession, book_id: int) -> Optional[models.Book]:
    """
    Retrieve a single book from the database by its ID.
    """
    result = await db.execute(select(models.Book).filter(models.Book.id == book_id))
    return result.scalars().first()


async def update_book(db: AsyncSession, book: models.Book, update_data: schemas.BookUpdate) -> models.Book:
    """
    Update a book record in the database.
    """
    update_data_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_data_dict.items():
        setattr(book, key, value)
    await db.commit()
    await db.refresh(book)
    return book


async def get_books_by_author(db: AsyncSession, author: str, skip: int = 0, limit: int = 100) -> List[models.Book]:
    """
    Retrieve books from the database by author.
    """
    result = await db.execute(select(models.Book).filter(models.Book.author.ilike(f"%{author}%")).offset(skip).limit(limit))
    return result.scalars().all()


async def create_book_log(db: AsyncSession, log: schemas.BookLogCreate) -> models.BookLog:
    """
    Create a new book log entry in the database.
    """
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
    task.completed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(task)


async def get_books_by_series(db: AsyncSession, series: str, skip: int = 0, limit: int = 100) -> List[models.Book]:
    """
    Retrieve books from the database by series.
    """
    result = await db.execute(select(models.Book).filter(models.Book.series.ilike(f"%{series}%")).offset(skip).limit(limit))
    return result.scalars().all()


async def create_cleaning_config(db: AsyncSession, config: schemas.CleaningConfigCreate) -> models.CleaningConfig:
    db_config = models.CleaningConfig(**config.model_dump())
    db.add(db_config)
    await db.commit()
    await db.refresh(db_config)
    return db_config


async def get_cleaning_configs(db: AsyncSession) -> List[models.CleaningConfig]:
    result = await db.execute(select(models.CleaningConfig))
    return result.scalars().all()


async def get_matching_cleaning_config(db: AsyncSession, url: str) -> Optional[models.CleaningConfig]:
    result = await db.execute(select(models.CleaningConfig))
    configs = result.scalars().all()
    for cfg in configs:
        if re.search(cfg.url_pattern, url):
            return cfg
    return None


async def get_cleaning_config(db: AsyncSession, config_id: int) -> Optional[models.CleaningConfig]:
    result = await db.execute(select(models.CleaningConfig).filter(models.CleaningConfig.id == config_id))
    return result.scalars().first()


async def update_cleaning_config(
    db: AsyncSession, config: models.CleaningConfig, update: schemas.CleaningConfigUpdate
) -> models.CleaningConfig:
    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)
    await db.commit()
    await db.refresh(config)
    return config


async def delete_cleaning_config(db: AsyncSession, config: models.CleaningConfig) -> None:
    await db.delete(config)
    await db.commit()
