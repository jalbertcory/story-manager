"""Catalog filtering, keyset pagination, and aggregate facets."""

from sqlalchemy import and_, asc, case, cast, desc, exists, func, literal, or_, select, true, union
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..catalog_pagination import seek_condition
from .series import _series_order_columns


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
    series: str | None = None,
    universe: int | None = None,
    source: str | None = None,
):
    conditions = [models.Book.deleted_at.is_(None)]
    if snapshot_max_id is not None:
        conditions.append(models.Book.id <= snapshot_max_id)
    if q and q.strip():
        from ..services.library import universe_expression

        pattern = f"%{q.strip().casefold()}%"
        matching_universe = select(models.Universe.id).where(models.Universe.name_key.ilike(pattern))
        conditions.append(or_(models.Book.catalog_search_text.ilike(pattern), universe_expression().in_(matching_universe)))

    if series is not None:
        conditions.append(func.lower(models.Book.series) == series.lower() if series else models.Book.series.is_(None))
    if universe is not None:
        from ..services.library import universe_expression

        conditions.append(universe_expression() == universe if universe else universe_expression().is_(None))
    if source:
        conditions.append(models.Book.source_type == models.SourceType(source))
        if source == "audiobook":
            conditions.append(models.Book.current_path.is_(None))

    has_audiobook = catalog_has_audiobook_expression()
    if audiobook in {"playable", "unplayable"}:
        from ..services.library import playable_audio_expression

        playable = playable_audio_expression()
        conditions.append(playable if audiobook == "playable" else ~playable)
    elif audiobook == "available":
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
        "series_index": func.coalesce(models.Book.series_index, 10000),
        "author": func.lower(func.coalesce(models.Book.author, "")),
        "word_count": func.coalesce(models.Book.current_word_count, -1),
        "updated_at": func.coalesce(models.Book.updated_at, models.Book.created_at),
        "audiobook_enabled": case((catalog_has_audiobook_expression(), 1), else_=0),
    }.get(sort_by, func.lower(func.coalesce(models.Book.title, "")))
    return primary, func.lower(func.coalesce(models.Book.title, "")), models.Book.id


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
        query = query.where(seek_condition(expressions, position, sort_order))
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
        groups = groups.having(seek_condition(expressions, position, sort_order))
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
