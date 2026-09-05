"""Universe organization and compact library group summaries."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models
from ..database import get_db
from ..services.library import library_book_info, library_groups

router = APIRouter(prefix="/api/library", tags=["library"])


class UniverseMembership(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    book_id: int | None = None
    series: str | None = None


@router.get("/groups")
async def groups(
    group_by: Literal["series", "universe"] = "series",
    q: str = "",
    universe: int | None = Query(default=None, ge=0),
    source: Literal["web", "epub"] | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await library_groups(db, group_by=group_by, q=q, universe=universe, source=source)


@router.get("/universes")
async def universes(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(models.Universe).order_by(models.Universe.name_key))).scalars()
    return [{"id": row.id, "name": row.name} for row in rows]


@router.get("/books/{book_id}/info")
async def book_info(book_id: int, db: AsyncSession = Depends(get_db)):
    if not await crud.get_book(db, book_id):
        raise HTTPException(404, "Book not found")
    return (await library_book_info(db, [book_id]))[book_id]


@router.put("/universe-membership")
async def set_membership(body: UniverseMembership, db: AsyncSession = Depends(get_db)):
    series = (body.series or "").strip()
    if bool(series) == (body.book_id is not None):
        raise HTTPException(422, "Choose either a series or a standalone book")
    book = None
    mapping = None
    if series:
        books = await crud.get_books_by_series(db, series, limit=1)
        if not books:
            raise HTTPException(404, "Series not found")
        series = books[0].series
        mapping = await db.get(models.UniverseSeries, series.lower())
    else:
        book = await crud.get_book(db, body.book_id)
        if not book:
            raise HTTPException(404, "Book not found")
        if book.series:
            raise HTTPException(409, "Assign the universe to this book's series instead")

    name = " ".join((body.name or "").split())
    universe = None
    if name:
        key = name.casefold()
        if len(key) > 200:
            raise HTTPException(422, "Universe name is too long")
        universe = (await db.execute(select(models.Universe).where(models.Universe.name_key == key))).scalar_one_or_none()
        if universe is None:
            try:
                async with db.begin_nested():
                    universe = models.Universe(name=name, name_key=key)
                    db.add(universe)
                    await db.flush()
            except IntegrityError:
                universe = (await db.execute(select(models.Universe).where(models.Universe.name_key == key))).scalar_one()
    if book:
        book.universe_id = universe.id if universe else None
    elif universe:
        if mapping:
            mapping.universe_id = universe.id
        else:
            db.add(models.UniverseSeries(series_key=series.lower(), universe_id=universe.id))
    elif mapping:
        await db.delete(mapping)
    await db.commit()
    return {"universe_id": universe.id if universe else None, "universe_name": universe.name if universe else None}


@router.get("/web-checks")
async def web_checks(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func

    latest = (
        select(
            models.BookLog.id,
            func.row_number()
            .over(partition_by=models.BookLog.book_id, order_by=(models.BookLog.timestamp.desc(), models.BookLog.id.desc()))
            .label("rank"),
        )
        .join(models.Book, models.Book.id == models.BookLog.book_id)
        .where(
            models.Book.deleted_at.is_(None),
            models.Book.source_type == models.SourceType.web,
            models.BookLog.entry_type.in_(["checked", "updated", "added", "error"]),
        )
        .subquery()
    )
    result = await db.execute(select(models.BookLog).join(latest, models.BookLog.id == latest.c.id).where(latest.c.rank == 1))
    return [
        {
            "book_id": row.book_id,
            "entry_type": row.entry_type,
            "timestamp": row.timestamp,
            "previous_chapter_count": row.previous_chapter_count,
            "new_chapter_count": row.new_chapter_count,
            "words_added": row.words_added,
        }
        for row in result.scalars()
    ]
