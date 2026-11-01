"""Lookups shared by the audiobook routers."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Book,
)


async def get_book_or_404(book_id: int, db: AsyncSession) -> Book:
    book = await db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


async def get_audiobook_book_or_404(book_id: int, db: AsyncSession) -> Book:
    book = await get_book_or_404(book_id, db)
    if not book.current_path:
        raise HTTPException(status_code=400, detail="AI narration requires book text")
    if not book.audiobook_enabled:
        raise HTTPException(status_code=403, detail="Audiobook pipeline is not enabled for this book")
    return book
