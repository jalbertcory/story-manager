"""Book CRUD operations: queries, creation, update, deletion."""

from typing import List, Optional
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, and_, asc, case, cast, delete, desc, exists, func, literal, or_, true, union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from .. import models, schemas


def _build_books_query(sort_by: str = "title", sort_order: str = "asc"):
    sort_columns = {
        "title": models.Book.title,
        "author": models.Book.author,
        "series": models.Book.series,
        "word_count": models.Book.current_word_count,
        "updated_at": models.Book.updated_at,
        "audiobook_enabled": models.Book.audiobook_enabled,
    }
    column = sort_columns.get(sort_by, models.Book.title)
    order = asc(column) if sort_order == "asc" else desc(column)
    return (
        select(models.Book)
        .where(models.Book.deleted_at.is_(None))
        .order_by(order, asc(models.Book.title), asc(models.Book.id))
    )


def _series_order_columns():
    return (
        asc(case((models.Book.series_index.is_(None), 1), else_=0)),
        asc(models.Book.series_index),
        asc(models.Book.title),
        asc(models.Book.id),
    )


def _build_book_search_query(q: str, sort_by: str = "title", sort_order: str = "asc"):
    pattern = f"%{q}%"
    return _build_books_query(sort_by=sort_by, sort_order=sort_order).filter(
        or_(
            models.Book.title.ilike(pattern),
            models.Book.author.ilike(pattern),
            models.Book.series.ilike(pattern),
            cast(models.Book.genre_tags, String).ilike(pattern),
            cast(models.Book.user_genre_tags, String).ilike(pattern),
        )
    )


async def get_book_by_source_url(
    db: AsyncSession,
    source_url: str,
    *,
    include_deleted: bool = True,
) -> Optional[models.Book]:
    """Retrieve a single book from the database by its source URL."""
    query = select(models.Book).filter(models.Book.source_url == source_url)
    if not include_deleted:
        query = query.filter(models.Book.deleted_at.is_(None))
    result = await db.execute(query)
    return result.scalars().first()


async def get_web_books(db: AsyncSession) -> List[models.Book]:
    """Retrieve all web books from the database."""
    result = await db.execute(
        select(models.Book).filter(
            models.Book.source_type == models.SourceType.web,
            models.Book.deleted_at.is_(None),
        )
    )
    return result.scalars().all()


async def get_pending_web_books(db: AsyncSession) -> List[models.Book]:
    """Return pending web books so they can be resumed by the import queue."""
    result = await db.execute(
        select(models.Book).filter(
            models.Book.source_type == models.SourceType.web,
            models.Book.download_status == "pending",
            models.Book.deleted_at.is_(None),
        )
    )
    return result.scalars().all()


async def get_pending_refresh_books(db: AsyncSession) -> List[models.Book]:
    """Return web books whose refresh job was in-flight, so the queue can resume them."""
    result = await db.execute(
        select(models.Book).filter(
            models.Book.source_type == models.SourceType.web,
            models.Book.refresh_status.in_(["queued", "processing"]),
            models.Book.deleted_at.is_(None),
        )
    )
    return result.scalars().all()


async def get_books(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    sort_by: str = "title",
    sort_order: str = "asc",
) -> List[models.Book]:
    """Retrieve a list of books from the database."""
    query = _build_books_query(sort_by=sort_by, sort_order=sort_order)
    result = await db.execute(query.offset(skip).limit(limit))
    return result.scalars().all()


async def search_books(db: AsyncSession, q: str, skip: int = 0, limit: int = 100) -> List[models.Book]:
    """Search books by title, author, or series (case-insensitive)."""
    result = await db.execute(_build_book_search_query(q=q).offset(skip).limit(limit))
    return result.scalars().all()


async def get_book_catalog(
    db: AsyncSession,
    q: Optional[str] = None,
    sort_by: str = "title",
    sort_order: str = "asc",
) -> List[models.Book]:
    query = (
        _build_book_search_query(q=q, sort_by=sort_by, sort_order=sort_order)
        if q
        else _build_books_query(
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )
    result = await db.execute(query)
    return result.scalars().all()


def catalog_has_audiobook_expression():
    return or_(
        models.Book.audiobook_enabled.is_(True),
        exists(select(models.ImportedAudiobook.id).where(models.ImportedAudiobook.book_id == models.Book.id)),
    )


def build_catalog_filter_conditions(
    *,
    q: str | None = None,
    view: str | None = None,
    review: str | None = None,
    audiobook: str | None = None,
    genre: str | None = None,
    snapshot_max_id: int | None = None,
):
    conditions = [models.Book.deleted_at.is_(None)]
    if snapshot_max_id is not None:
        conditions.append(models.Book.id <= snapshot_max_id)
    if q and q.strip():
        conditions.append(models.Book.catalog_search_text.ilike(f"%{q.strip().casefold()}%"))

    has_audiobook = catalog_has_audiobook_expression()
    if audiobook == "available":
        conditions.append(has_audiobook)
    elif audiobook == "none":
        conditions.append(~has_audiobook)

    if review == "missing-series":
        conditions.extend(
            [
                models.Book.series.is_(None),
                models.Book.source_type != models.SourceType.web,
                models.Book.download_status.is_(None),
            ]
        )
    elif review == "refreshing":
        conditions.append(models.Book.refresh_status.in_(["queued", "processing"]))
    elif review == "refresh-error":
        conditions.append(models.Book.refresh_status == "error")

    if genre and genre.strip():
        # Facet values originate from these arrays, so an exact, normalized
        # token match is sufficient without casting JSON in the search path.
        token = genre.strip().casefold()
        conditions.append(models.Book.catalog_search_text.like(f"%tag:{token}\n%"))

    if view == "series":
        conditions.extend([models.Book.series.is_not(None), models.Book.download_status.is_(None)])
    elif view == "standalone":
        conditions.extend(
            [
                models.Book.source_type != models.SourceType.web,
                or_(models.Book.series.is_(None), models.Book.download_status.is_not(None)),
            ]
        )
    elif view == "web":
        conditions.extend([models.Book.source_type == models.SourceType.web, models.Book.download_status.is_(None)])
    return conditions


def _catalog_book_sort_expressions(sort_by: str):
    primary = {
        "author": func.lower(func.coalesce(models.Book.author, "")),
        "word_count": func.coalesce(models.Book.current_word_count, -1),
        "updated_at": func.coalesce(models.Book.updated_at, models.Book.created_at),
        "audiobook_enabled": case((catalog_has_audiobook_expression(), 1), else_=0),
    }.get(sort_by, func.lower(func.coalesce(models.Book.title, "")))
    return primary, func.lower(func.coalesce(models.Book.title, "")), models.Book.id


def _seek_condition(expressions, values, sort_order: str):
    primary, title, identifier = expressions
    primary_value, title_value, identifier_value = values
    primary_after = primary < primary_value if sort_order == "desc" else primary > primary_value
    return or_(
        primary_after,
        and_(
            primary == primary_value,
            or_(title > title_value, and_(title == title_value, identifier > identifier_value)),
        ),
    )


async def get_catalog_book_page(
    db: AsyncSession,
    *,
    conditions,
    sort_by: str,
    sort_order: str,
    limit: int,
    position: list | None,
) -> tuple[list[models.Book], bool]:
    expressions = _catalog_book_sort_expressions(sort_by)
    primary_order = desc(expressions[0]) if sort_order == "desc" else asc(expressions[0])
    query = select(models.Book).where(*conditions)
    if position is not None:
        query = query.where(_seek_condition(expressions, position, sort_order))
    result = await db.execute(query.order_by(primary_order, asc(expressions[1]), asc(expressions[2])).limit(limit + 1))
    books = list(result.scalars().all())
    return books[:limit], len(books) > limit


def _catalog_series_sort_expressions(sort_by: str):
    primary = {
        "author": func.min(func.lower(func.coalesce(models.Book.author, ""))),
        "word_count": func.sum(func.coalesce(models.Book.current_word_count, 0)),
        "updated_at": func.max(func.coalesce(models.Book.updated_at, models.Book.created_at)),
        "audiobook_enabled": func.max(case((catalog_has_audiobook_expression(), 1), else_=0)),
    }.get(sort_by, func.lower(models.Book.series))
    return primary, func.lower(models.Book.series), func.min(models.Book.id)


async def get_catalog_series_page(
    db: AsyncSession,
    *,
    conditions,
    sort_by: str,
    sort_order: str,
    limit: int,
    position: list | None,
) -> tuple[list[models.Book], bool, list]:
    expressions = _catalog_series_sort_expressions(sort_by)
    primary_order = desc(expressions[0]) if sort_order == "desc" else asc(expressions[0])
    groups = (
        select(
            models.Book.series.label("series"),
            expressions[0].label("sort_value"),
            expressions[1].label("title_value"),
            expressions[2].label("id_value"),
        )
        .where(*conditions)
        .group_by(models.Book.series)
    )
    if position is not None:
        groups = groups.having(_seek_condition(expressions, position, sort_order))
    result = await db.execute(groups.order_by(primary_order, asc(expressions[1]), asc(expressions[2])).limit(limit + 1))
    rows = list(result.all())
    page_rows = rows[:limit]
    if not page_rows:
        return [], False, []

    names = [row.series for row in page_rows]
    book_result = await db.execute(
        select(models.Book).where(*conditions, models.Book.series.in_(names)).order_by(*_series_order_columns())
    )
    by_series: dict[str, list[models.Book]] = {name: [] for name in names}
    for book in book_result.scalars().all():
        by_series[book.series].append(book)
    books = [book for name in names for book in by_series[name]]
    last = page_rows[-1]
    return books, len(rows) > limit, [last.sort_value, last.title_value, last.id_value]


async def get_catalog_snapshot_max_id(db: AsyncSession) -> int:
    result = await db.execute(select(func.coalesce(func.max(models.Book.id), 0)).where(models.Book.deleted_at.is_(None)))
    return int(result.scalar_one())


async def get_catalog_total_count(db: AsyncSession, *, conditions, view: str) -> int:
    expression = func.count(func.distinct(models.Book.series)) if view == "series" else func.count(models.Book.id)
    result = await db.execute(select(expression).where(*conditions))
    return int(result.scalar_one() or 0)


async def get_catalog_facets(db: AsyncSession, *, conditions, genre_conditions=None) -> dict:
    has_audio = catalog_has_audiobook_expression()
    series_condition = and_(models.Book.series.is_not(None), models.Book.download_status.is_(None))
    standalone_condition = and_(
        models.Book.source_type != models.SourceType.web,
        or_(models.Book.series.is_(None), models.Book.download_status.is_not(None)),
    )
    web_condition = and_(
        models.Book.source_type == models.SourceType.web,
        models.Book.download_status.is_(None),
    )
    row = (
        await db.execute(
            select(
                func.count(func.distinct(case((series_condition, models.Book.series)))).label("series"),
                func.sum(case((standalone_condition, 1), else_=0)).label("standalone"),
                func.sum(case((web_condition, 1), else_=0)).label("web"),
                func.sum(case((has_audio, 1), else_=0)).label("audiobook_available"),
                func.sum(case((~has_audio, 1), else_=0)).label("audiobook_missing"),
                func.sum(
                    case(
                        (
                            and_(
                                models.Book.series.is_(None),
                                models.Book.source_type != models.SourceType.web,
                                models.Book.download_status.is_(None),
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("missing_series"),
                func.sum(case((models.Book.refresh_status.in_(["queued", "processing"]), 1), else_=0)).label("refreshing"),
                func.sum(case((models.Book.refresh_status == "error", 1), else_=0)).label("refresh_attention"),
            ).where(*conditions)
        )
    ).one()

    def tag_values(column):
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB

            return func.jsonb_array_elements_text(func.coalesce(cast(column, JSONB), literal([], type_=JSONB))).table_valued(
                "value"
            )
        return func.json_each(func.coalesce(column, "[]")).table_valued("key", "value")

    tag_selects = []
    tag_conditions = genre_conditions if genre_conditions is not None else conditions
    for column in (models.Book.genre_tags, models.Book.user_genre_tags):
        values = tag_values(column)
        tag_selects.append(
            select(
                models.Book.id.label("book_id"),
                func.lower(values.c.value).label("folded"),
                values.c.value.label("display"),
            )
            .select_from(models.Book)
            .join(values, true())
            .where(*tag_conditions, values.c.value.is_not(None), values.c.value != "")
        )
    tags = union(*tag_selects).subquery()
    genre_rows = await db.execute(
        select(func.min(tags.c.display), func.count()).group_by(tags.c.folded).order_by(tags.c.folded)
    )

    return {
        "series": int(row.series or 0),
        "standalone": int(row.standalone or 0),
        "web": int(row.web or 0),
        "audiobook_available": int(row.audiobook_available or 0),
        "audiobook_missing": int(row.audiobook_missing or 0),
        "missing_series": int(row.missing_series or 0),
        "refreshing": int(row.refreshing or 0),
        "refresh_attention": int(row.refresh_attention or 0),
        "genres": [{"name": display, "count": int(count)} for display, count in genre_rows],
    }


async def create_book(db: AsyncSession, book: schemas.BookCreate) -> models.Book:
    """Create a new book record in the database."""
    book_data = book.model_dump(exclude_unset=True)
    if "source_url" in book_data and book_data["source_url"] is not None:
        book_data["source_url"] = str(book_data["source_url"])
    book_data.setdefault("content_updated_at", datetime.now(timezone.utc))
    book_data.setdefault("content_version", 1)

    db_book = models.Book(**book_data)
    db.add(db_book)
    await db.commit()
    await db.refresh(db_book)
    return db_book


async def get_book(db: AsyncSession, book_id: int, *, include_deleted: bool = False) -> Optional[models.Book]:
    """Retrieve a single book from the database by its ID."""
    query = select(models.Book).filter(models.Book.id == book_id)
    if not include_deleted:
        query = query.filter(models.Book.deleted_at.is_(None))
    result = await db.execute(query)
    return result.scalars().first()


async def get_books_by_ids(db: AsyncSession, book_ids: List[int]) -> List[models.Book]:
    if not book_ids:
        return []

    result = await db.execute(
        select(models.Book).filter(
            models.Book.id.in_(book_ids),
            models.Book.deleted_at.is_(None),
        )
    )
    books = {book.id: book for book in result.scalars().all()}
    return [books[book_id] for book_id in book_ids if book_id in books]


async def update_book(db: AsyncSession, book: models.Book, update_data: schemas.BookUpdate) -> models.Book:
    """Update a book record in the database."""
    update_data_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_data_dict.items():
        setattr(book, key, value)
    if "series" in update_data_dict and not update_data_dict["series"]:
        book.series_index = None
    await db.commit()
    await db.refresh(book)
    return book


async def reset_failed_web_book_for_retry(
    db: AsyncSession,
    book: models.Book,
    source_url: str,
) -> models.Book:
    """Reuse a failed web-import placeholder so the same URL can be retried."""
    book.title = source_url
    book.author = "Pending"
    book.series = None
    book.series_index = None
    book.genre_tags = []
    book.source_tags = []
    book.cover_path = None
    book.immutable_path = None
    book.current_path = None
    book.master_word_count = None
    book.current_word_count = None
    book.removed_chapters = []
    book.content_selectors = []
    book.download_status = "pending"
    book.source_url = source_url
    book.source_type = models.SourceType.web
    await db.commit()
    await db.refresh(book)
    return book


async def detach_book_source(db: AsyncSession, book: models.Book) -> models.Book:
    """Clear a book's remote source metadata and treat it as a normal EPUB."""
    book.source_url = None
    book.source_type = models.SourceType.epub
    book.download_status = None
    await db.commit()
    await db.refresh(book)
    return book


async def touch_book_content(db: AsyncSession, book: models.Book) -> None:
    book.content_updated_at = datetime.now(timezone.utc)
    book.content_version = (book.content_version or 0) + 1
    if book.audiobook_enabled:
        book.audiobook_pending_content_version = max(
            book.audiobook_pending_content_version or 0,
            book.content_version,
        )
        if book.audiobook_revision or book.audiobook_source_content_version is not None:
            book.audiobook_publication_state = "stale"


async def get_books_by_author(db: AsyncSession, author: str, skip: int = 0, limit: int = 100) -> List[models.Book]:
    """Retrieve books from the database by author."""
    result = await db.execute(
        select(models.Book)
        .filter(models.Book.author.ilike(f"%{author}%"), models.Book.deleted_at.is_(None))
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def get_book_by_title(
    db: AsyncSession,
    title: str,
    *,
    include_deleted: bool = False,
) -> Optional[models.Book]:
    """Retrieve a single book from the database by its title."""
    query = select(models.Book).filter(models.Book.title == title)
    if not include_deleted:
        query = query.filter(models.Book.deleted_at.is_(None))
    result = await db.execute(query)
    return result.scalars().first()


async def get_book_by_title_and_author(
    db: AsyncSession,
    title: str,
    author: str,
    *,
    include_deleted: bool = True,
) -> Optional[models.Book]:
    """Retrieve a book by exact (case-insensitive) title and author match."""
    query = select(models.Book).where(
        func.lower(models.Book.title) == title.lower(),
        func.lower(models.Book.author) == author.lower(),
    )
    if not include_deleted:
        query = query.where(models.Book.deleted_at.is_(None))
    result = await db.execute(query)
    return result.scalars().first()


async def delete_book(db: AsyncSession, book: models.Book) -> None:
    """Delete a book record from the database."""
    await db.execute(delete(models.MetadataProposal).where(models.MetadataProposal.book_id == book.id))
    await db.execute(delete(models.BookMetadataMatch).where(models.BookMetadataMatch.book_id == book.id))
    await db.execute(delete(models.BookLog).where(models.BookLog.book_id == book.id))
    await db.delete(book)
    await db.commit()


async def recycle_book(db: AsyncSession, book: models.Book, *, retention_days: int) -> models.Book:
    """Hide a book from the live library while preserving its files and history."""
    now = datetime.now(timezone.utc)
    book.deleted_at = now
    book.purge_after = now + timedelta(days=retention_days)
    await db.commit()
    await db.refresh(book)
    return book


async def restore_recycled_book(db: AsyncSession, book: models.Book) -> models.Book:
    book.deleted_at = None
    book.purge_after = None
    await db.commit()
    await db.refresh(book)
    return book


async def get_recycled_books(db: AsyncSession) -> List[models.Book]:
    result = await db.execute(
        select(models.Book)
        .where(models.Book.deleted_at.isnot(None))
        .order_by(desc(models.Book.deleted_at), asc(models.Book.title))
    )
    return list(result.scalars().all())


async def get_all_books_including_deleted(db: AsyncSession) -> List[models.Book]:
    result = await db.execute(select(models.Book))
    return list(result.scalars().all())


async def recycle_all_books(db: AsyncSession, *, retention_days: int) -> int:
    books = await get_books(db, limit=100000)
    if not books:
        return 0
    now = datetime.now(timezone.utc)
    purge_after = now + timedelta(days=retention_days)
    for book in books:
        book.deleted_at = now
        book.purge_after = purge_after
    await db.commit()
    return len(books)


async def delete_all_books(db: AsyncSession) -> int:
    books = await get_books(db, limit=100000)
    book_count = len(books)
    if book_count == 0:
        return 0

    book_ids = [book.id for book in books]
    await db.execute(delete(models.MetadataProposal).where(models.MetadataProposal.book_id.in_(book_ids)))
    await db.execute(delete(models.BookMetadataMatch).where(models.BookMetadataMatch.book_id.in_(book_ids)))
    await db.execute(delete(models.BookLog).where(models.BookLog.book_id.in_(book_ids)))
    await db.execute(delete(models.Book))
    await db.commit()
    return book_count


async def count_books(db: AsyncSession, q: Optional[str] = None) -> int:
    """Count books, optionally filtered by a search query (title/author/series)."""
    if q:
        pattern = f"%{q}%"
        result = await db.execute(
            select(func.count(models.Book.id)).filter(
                models.Book.deleted_at.is_(None),
                or_(
                    models.Book.title.ilike(pattern),
                    models.Book.author.ilike(pattern),
                    models.Book.series.ilike(pattern),
                    cast(models.Book.genre_tags, String).ilike(pattern),
                    cast(models.Book.user_genre_tags, String).ilike(pattern),
                ),
            )
        )
    else:
        result = await db.execute(select(func.count(models.Book.id)).filter(models.Book.deleted_at.is_(None)))
    return result.scalar() or 0


async def get_books_without_series(db: AsyncSession) -> List[models.Book]:
    """Retrieve all books that have no series assigned."""
    result = await db.execute(select(models.Book).filter(models.Book.series.is_(None), models.Book.deleted_at.is_(None)))
    return result.scalars().all()
