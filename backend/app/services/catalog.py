"""Catalog serialization helpers for the library views."""

from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas


def normalize_genre_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        cleaned = raw_tag.strip()
        if not cleaned:
            continue
        folded = cleaned.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        normalized.append(cleaned)
    return sorted(normalized, key=str.casefold)


def effective_genre_tags(book: models.Book, series_user_genre_tags: list[str] | None = None) -> list[str]:
    return normalize_genre_tags(
        [
            *(series_user_genre_tags or []),
            *(book.user_genre_tags or []),
            *(book.genre_tags or []),
        ]
    )


async def _series_metadata_map(
    db: AsyncSession,
    books: list[models.Book],
) -> dict[str, models.SeriesMetadata]:
    series_names = sorted({book.series for book in books if book.series})
    return await crud.get_series_metadata_for_names(db, series_names)


def serialize_catalog_book(
    book: models.Book,
    *,
    series_user_genre_tags: list[str] | None = None,
    effective_series_genre_tags: list[str] | None = None,
) -> schemas.BookCatalogEntry:
    payload = schemas.BookCatalogEntry.model_validate(book).model_dump()
    payload["series_user_genre_tags"] = series_user_genre_tags or []
    payload["effective_genre_tags"] = effective_genre_tags(book, series_user_genre_tags)
    payload["effective_series_genre_tags"] = effective_series_genre_tags or []
    return schemas.BookCatalogEntry.model_validate(payload)


async def build_book_catalog(
    db: AsyncSession,
    *,
    q: str | None = None,
    sort_by: str = "title",
    sort_order: str = "asc",
) -> list[schemas.BookCatalogEntry]:
    books = await crud.get_book_catalog(db, q=q, sort_by=sort_by, sort_order=sort_order)
    metadata_map = await _series_metadata_map(db, books)

    series_books: dict[str, list[models.Book]] = {}
    for book in books:
        if book.series:
            series_books.setdefault(book.series, []).append(book)

    effective_series_tags: dict[str, list[str]] = {}
    for series_name, group in series_books.items():
        meta = metadata_map.get(series_name)
        effective_series_tags[series_name] = crud.compute_effective_series_genre_tags(group, meta)

    return [
        serialize_catalog_book(
            book,
            series_user_genre_tags=(metadata_map.get(book.series).user_genre_tags if book.series in metadata_map else []),
            effective_series_genre_tags=effective_series_tags.get(book.series, []) if book.series else [],
        )
        for book in books
    ]
