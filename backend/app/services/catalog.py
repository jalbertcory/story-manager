"""Paginated catalog serialization helpers for the library views."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime

from fastapi import HTTPException
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


def serialize_catalog_book(
    book: models.Book,
    *,
    audiobook_types: list[schemas.AudiobookType] | None = None,
    series_user_genre_tags: list[str] | None = None,
    effective_series_genre_tags: list[str] | None = None,
) -> schemas.BookCatalogEntry:
    payload = schemas.BookCatalogEntry.model_validate(book).model_dump()
    payload["audiobook_types"] = audiobook_types or []
    payload["series_user_genre_tags"] = series_user_genre_tags or []
    payload["effective_genre_tags"] = effective_genre_tags(book, series_user_genre_tags)
    payload["effective_series_genre_tags"] = effective_series_genre_tags or []
    return schemas.BookCatalogEntry.model_validate(payload)


def _cursor_signature(params: dict) -> str:
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _json_value(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _encode_cursor(*, snapshot_max_id: int, position: list, signature: str) -> str:
    payload = {
        "v": 1,
        "snapshot_max_id": snapshot_max_id,
        "position": [_json_value(value) for value in position],
        "signature": signature,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, *, signature: str, sort_by: str) -> tuple[int, list]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw)
        if payload.get("v") != 1 or payload.get("signature") != signature:
            raise ValueError
        snapshot_max_id = int(payload["snapshot_max_id"])
        position = payload["position"]
        if not isinstance(position, list) or len(position) != 3:
            raise ValueError
        if sort_by == "updated_at":
            position[0] = datetime.fromisoformat(position[0])
        return snapshot_max_id, position
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or stale catalog cursor") from exc


def _book_position(
    book: models.Book,
    *,
    sort_by: str,
    human_audiobook_book_ids: set[int],
) -> list:
    primary = {
        "author": (book.author or "").lower(),
        "word_count": book.current_word_count if book.current_word_count is not None else -1,
        "updated_at": book.updated_at or book.created_at,
        "audiobook_enabled": int(book.audiobook_enabled or book.id in human_audiobook_book_ids),
    }.get(sort_by, (book.title or "").lower())
    return [primary, (book.title or "").lower(), book.id]


async def build_book_catalog_page(
    db: AsyncSession,
    *,
    q: str | None = None,
    view: str = "series",
    review: str | None = None,
    audiobook: str | None = None,
    genre: str | None = None,
    sort_by: str = "title",
    sort_order: str = "asc",
    limit: int = 30,
    cursor: str | None = None,
) -> schemas.BookCatalogPage:
    cursor_params = {
        "q": (q or "").strip().casefold(),
        "view": view,
        "review": review or "",
        "audiobook": audiobook or "",
        "genre": (genre or "").strip().casefold(),
        "sort_by": sort_by,
        "sort_order": sort_order,
        "limit": limit,
    }
    signature = _cursor_signature(cursor_params)
    if cursor:
        snapshot_max_id, position = _decode_cursor(cursor, signature=signature, sort_by=sort_by)
    else:
        snapshot_max_id = await crud.get_catalog_snapshot_max_id(db)
        position = None

    facet_conditions = crud.build_catalog_filter_conditions(
        q=q,
        review=review,
        audiobook=audiobook,
        genre=genre,
        snapshot_max_id=snapshot_max_id,
    )
    genre_facet_conditions = crud.build_catalog_filter_conditions(
        q=q,
        review=review,
        audiobook=audiobook,
        snapshot_max_id=snapshot_max_id,
    )
    conditions = crud.build_catalog_filter_conditions(
        q=q,
        view=view,
        review=review,
        audiobook=audiobook,
        genre=genre,
        snapshot_max_id=snapshot_max_id,
    )

    if view == "series":
        books, has_more, last_position = await crud.get_catalog_series_page(
            db,
            conditions=conditions,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            position=position,
        )
    else:
        books, has_more = await crud.get_catalog_book_page(
            db,
            conditions=conditions,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            position=position,
        )
        last_position = []

    metadata_map = await crud.get_series_metadata_for_names(db, sorted({book.series for book in books if book.series}))
    human_ids = await crud.audiobook.get_human_audiobook_book_ids(db, [book.id for book in books])

    series_books: dict[str, list[models.Book]] = {}
    for book in books:
        if book.series:
            series_books.setdefault(book.series, []).append(book)
    effective_series_tags = {
        series_name: crud.compute_effective_series_genre_tags(group, metadata_map.get(series_name))
        for series_name, group in series_books.items()
    }

    items = [
        serialize_catalog_book(
            book,
            audiobook_types=[
                *(["ai_generated"] if book.audiobook_enabled else []),
                *(["human_narrated"] if book.id in human_ids else []),
            ],
            series_user_genre_tags=(metadata_map.get(book.series).user_genre_tags if book.series in metadata_map else []),
            effective_series_genre_tags=effective_series_tags.get(book.series, []) if book.series else [],
        )
        for book in books
    ]

    next_cursor = None
    if has_more and books:
        if view != "series":
            last_position = _book_position(books[-1], sort_by=sort_by, human_audiobook_book_ids=human_ids)
        next_cursor = _encode_cursor(
            snapshot_max_id=snapshot_max_id,
            position=last_position,
            signature=signature,
        )

    facets = await crud.get_catalog_facets(
        db,
        conditions=facet_conditions,
        genre_conditions=genre_facet_conditions,
    )
    total_count = await crud.get_catalog_total_count(db, conditions=conditions, view=view)
    return schemas.BookCatalogPage(
        items=items,
        next_cursor=next_cursor,
        total_count=total_count,
        facets=schemas.BookCatalogFacets.model_validate(facets),
    )
