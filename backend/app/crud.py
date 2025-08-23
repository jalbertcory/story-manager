from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from . import models, schemas

async def get_book_by_source_url(db: AsyncSession, source_url: str) -> Optional[models.Book]:
    """
    Retrieve a single book from the database by its source URL.
    """
    result = await db.execute(select(models.Book).filter(models.Book.source_url == source_url))
    return result.scalars().first()

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
    book_data = book.model_dump()
    if book.source_url:
        book_data["source_url"] = str(book.source_url)

    db_book = models.Book(**book_data)
    db.add(db_book)
    await db.commit()
    await db.refresh(db_book)
    return db_book

async def get_books_by_author(db: AsyncSession, author: str, skip: int = 0, limit: int = 100) -> List[models.Book]:
    """
    Retrieve books from the database by author.
    """
    result = await db.execute(
        select(models.Book)
        .filter(models.Book.author.ilike(f"%{author}%"))
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

async def get_books_by_series(db: AsyncSession, series: str, skip: int = 0, limit: int = 100) -> List[models.Book]:
    """
    Retrieve books from the database by series.
    """
    result = await db.execute(
        select(models.Book)
        .filter(models.Book.series.ilike(f"%{series}%"))
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()
