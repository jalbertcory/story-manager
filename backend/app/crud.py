from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from . import models, schemas

async def get_book_by_source_url(db: AsyncSession, source_url: str):
    """
    Retrieve a single book from the database by its source URL.
    """
    result = await db.execute(select(models.Book).filter(models.Book.source_url == source_url))
    return result.scalars().first()

async def get_books(db: AsyncSession, skip: int = 0, limit: int = 100):
    """
    Retrieve a list of books from the database.
    """
    result = await db.execute(select(models.Book).offset(skip).limit(limit))
    return result.scalars().all()

async def create_book(db: AsyncSession, book: schemas.BookCreate):
    """
    Create a new book record in the database.
    """
    # The source_url from the schema is a Pydantic HttpUrl.
    # We need to convert it to a string before saving to the database.
    book_data = book.model_dump()
    book_data["source_url"] = str(book.source_url)

    db_book = models.Book(**book_data)
    db.add(db_book)
    await db.commit()
    await db.refresh(db_book)
    return db_book
