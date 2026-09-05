"""Filtered group summaries with bounded payloads and stable cursor traversal."""

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..crud.catalog import build_catalog_filter_conditions, get_catalog_facets, get_catalog_snapshot_max_id
from ..catalog_pagination import cursor_signature, decode_cursor, encode_cursor, seek_condition


async def library_groups(
    db: AsyncSession,
    *,
    group_by: str,
    q: str,
    universe: int | None,
    source: str | None,
    genre: str | None = None,
    audiobook: str | None = None,
    review: str | None = None,
    sort_by: str = "title",
    sort_order: str = "asc",
    limit: int | None = None,
    cursor: str | None = None,
):
    from .library import universe_expression, playable_audio_expression

    filters = dict(q=q, universe=universe, source=source, genre=genre, audiobook=audiobook, review=review)
    signature = cursor_signature(dict(**filters, group_by=group_by, sort_by=sort_by, sort_order=sort_order, limit=limit))
    if cursor:
        snapshot, position = decode_cursor(cursor, signature=signature, sort_by=sort_by)
    else:
        snapshot, position = await get_catalog_snapshot_max_id(db), None
    conditions = build_catalog_filter_conditions(**filters, snapshot_max_id=snapshot)
    key = func.lower(models.Book.series) if group_by == "series" else models.Universe.name
    display_name = func.min(models.Book.series) if group_by == "series" else models.Universe.name
    aggregate = (
        select(
            display_name.label("name"),
            func.count(models.Book.id).label("book_count"),
            func.min(models.Book.author).label("author"),
            func.count(func.distinct(models.Book.author)).label("author_count"),
            func.sum(case((playable_audio_expression(), 1), else_=0)).label("audio_count"),
            func.min(models.Universe.id).label("universe_id"),
            func.sum(func.coalesce(models.Book.current_word_count, 0)).label("word_count"),
            func.max(func.coalesce(models.Book.updated_at, models.Book.created_at)).label("updated_at"),
            func.min(models.Book.id).label("first_id"),
        )
        .select_from(models.Book)
        .outerjoin(models.Universe, models.Universe.id == universe_expression())
        .where(*conditions)
        .group_by(key)
        .subquery()
    )
    # Prefix the name to keep the unassigned group last without colliding with real names.
    name = case((aggregate.c.name.is_(None), "1"), else_="0" + func.lower(aggregate.c.name))
    primary = {
        "author": func.lower(func.coalesce(aggregate.c.author, "")),
        "word_count": aggregate.c.word_count,
        "updated_at": aggregate.c.updated_at,
    }.get(sort_by, name)
    expressions = (primary, name, aggregate.c.first_id)
    query = select(aggregate, primary.label("sort_value"), name.label("name_value"))
    if position is not None:
        query = query.where(seek_condition(expressions, position, sort_order))
    query = query.order_by(primary.desc() if sort_order == "desc" else primary.asc(), name, aggregate.c.first_id)
    if limit is not None:
        query = query.limit(limit + 1)
    rows = list((await db.execute(query)).all())
    has_more = limit is not None and len(rows) > limit
    rows = rows[:limit] if limit is not None else rows
    groups = [dict(row._mapping) for row in rows]

    # Rank covers only for the groups on this page.
    page_keys = [g["name"].lower() if group_by == "series" else g["name"] for g in groups if g["name"] is not None]
    page_condition = key.in_(page_keys)
    if any(g["name"] is None for g in groups):
        page_condition = page_condition | key.is_(None)
    covers = (
        select(
            key.label("name"),
            models.Book.id,
            func.row_number()
            .over(partition_by=key, order_by=(models.Book.series_index.asc().nulls_last(), models.Book.id))
            .label("rank"),
        )
        .select_from(models.Book)
        .outerjoin(models.Universe, models.Universe.id == universe_expression())
        .where(*conditions, page_condition, models.Book.cover_path.is_not(None))
        .subquery()
    )
    cover_map = {}
    if groups:
        for row in await db.execute(select(covers).where(covers.c.rank <= 3).order_by(covers.c.rank)):
            cover_map.setdefault(row.name, []).append(row.id)
    next_cursor = None
    if has_more:
        last = groups[-1]
        next_cursor = encode_cursor(
            snapshot_max_id=snapshot,
            signature=signature,
            position=[last["sort_value"], last["name_value"], last["first_id"]],
        )
    for group in groups:
        cover_key = group["name"].lower() if group_by == "series" and group["name"] else group["name"]
        group["cover_ids"] = cover_map.get(cover_key, [])
        for internal in ("sort_value", "name_value", "first_id", "word_count", "updated_at"):
            group.pop(internal)
    if limit is None:
        return groups
    genre_conditions = build_catalog_filter_conditions(**{**filters, "genre": None}, snapshot_max_id=snapshot)
    return {
        "items": groups,
        "next_cursor": next_cursor,
        "total_count": await db.scalar(select(func.count()).select_from(aggregate)),
        "facets": await get_catalog_facets(db, conditions=conditions, genre_conditions=genre_conditions),
    }
