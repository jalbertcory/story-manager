"""Series gap detection and new/upcoming release discovery.

Gaps ("you have books 1, 2 and 4") are derived purely from the library. Releases
are a best-effort Google Books lookup per series: it only sees volumes whose
title or subtitle names the series, and publication dates are whatever the
publisher supplied, so results are hints rather than a complete catalogue.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Awaitable, Callable

import requests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..database import SessionLocal
from .metadata.clients import google_books_enabled, request_google_books_json
from .metadata.responses import GOOGLE_VOLUME, valid_records
from .metadata.scoring import best_author_similarity, infer_series_metadata, normalize_text, title_similarity
from .notifications import EVENT_SERIES_UPDATE, emit_notification

logger = logging.getLogger(__name__)

# A series whose numbering skips more volumes than this is assumed not to be
# numbered sequentially (e.g. publication-order numbers across a shared universe).
MAX_GAPS_PER_SERIES = 10
MAX_POSSIBLE_TITLES = 5
MAX_RELEASE_SERIES_PER_RUN = 60
# Releases older than this at discovery are back catalogue, not news.
RELEASE_LOOKBACK = timedelta(days=90)
_AUTHOR_MATCH_THRESHOLD = 0.8
_OWNED_TITLE_THRESHOLD = 0.85
_NOTIFICATION_LINE_LIMIT = 12

ProgressCallback = Callable[[int, int, str], Awaitable[None]]


@dataclass
class TrackedSeries:
    key: str
    name: str
    author: str
    titles: list[str]
    book_ids: list[int]
    whole_indexes: set[int]
    has_published_book: bool


@dataclass
class SeriesGap:
    series_name: str
    author: str
    missing_indexes: list[int]
    owned_count: int
    possible_titles: list[str] = field(default_factory=list)


@dataclass
class ReleaseCandidate:
    title: str
    published_date: str
    release_date: date
    series_index: float | None
    remote_url: str | None


def series_key(name: str) -> str:
    return normalize_text(name)


def gap_finding_key(series_name: str, index: int) -> str:
    return f"gap:{series_key(series_name)}:{index}"


def release_finding_key(series_name: str, title: str) -> str:
    return f"release:{series_key(series_name)}:{normalize_text(title)}"


def _most_common(values: list[str]) -> str:
    cleaned = [value.strip() for value in values if value and value.strip()]
    return Counter(cleaned).most_common(1)[0][0] if cleaned else ""


async def load_tracked_series(db: AsyncSession) -> list[TrackedSeries]:
    rows = (
        await db.execute(
            select(
                models.Book.id,
                models.Book.title,
                models.Book.author,
                models.Book.series,
                models.Book.series_index,
                models.Book.source_type,
            ).where(models.Book.deleted_at.is_(None), models.Book.series.isnot(None))
        )
    ).all()
    grouped: dict[str, list[tuple[int, str, str, str, Decimal | None, models.SourceType]]] = defaultdict(list)
    for book_id, title, author, series, index, source_type in rows:
        key = series_key(series or "")
        if key:
            grouped[key].append((book_id, title or "", author or "", series or "", index, source_type))

    tracked: list[TrackedSeries] = []
    for key, books in grouped.items():
        whole_indexes = {
            int(index) for _, _, _, _, index, _ in books if index is not None and index >= 1 and index == int(index)
        }
        tracked.append(
            TrackedSeries(
                key=key,
                name=_most_common([book[3] for book in books]),
                author=_most_common([book[2] for book in books]),
                titles=[book[1] for book in books if book[1]],
                book_ids=[book[0] for book in books],
                whole_indexes=whole_indexes,
                has_published_book=any(book[5] != models.SourceType.web for book in books),
            )
        )
    tracked.sort(key=lambda item: item.name.casefold())
    return tracked


def missing_indexes(whole_indexes: set[int]) -> list[int]:
    if not whole_indexes:
        return []
    missing = [index for index in range(1, max(whole_indexes) + 1) if index not in whole_indexes]
    return missing if len(missing) <= MAX_GAPS_PER_SERIES else []


async def _possible_titles(db: AsyncSession, book_ids: list[int], owned_titles: list[str]) -> list[str]:
    if not book_ids:
        return []
    rows = (
        await db.execute(
            select(models.BookMetadataMatch.possible_missing_series_books).where(
                models.BookMetadataMatch.book_id.in_(book_ids)
            )
        )
    ).all()
    titles: dict[str, str] = {}
    for (candidates,) in rows:
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            if any(title_similarity(candidate, owned) >= _OWNED_TITLE_THRESHOLD for owned in owned_titles):
                continue
            titles.setdefault(normalize_text(candidate), candidate.strip())
    return sorted(titles.values(), key=str.casefold)[:MAX_POSSIBLE_TITLES]


async def compute_series_gaps(db: AsyncSession, *, include_dismissed: bool = False) -> list[SeriesGap]:
    dismissed: set[str] = set()
    if not include_dismissed:
        dismissed = set(
            (
                await db.execute(
                    select(models.SeriesFinding.finding_key).where(
                        models.SeriesFinding.kind == "gap", models.SeriesFinding.status == "dismissed"
                    )
                )
            )
            .scalars()
            .all()
        )
    gaps: list[SeriesGap] = []
    for series in await load_tracked_series(db):
        missing = [
            index for index in missing_indexes(series.whole_indexes) if gap_finding_key(series.name, index) not in dismissed
        ]
        if not missing:
            continue
        gaps.append(
            SeriesGap(
                series_name=series.name,
                author=series.author,
                missing_indexes=missing,
                owned_count=len(series.book_ids),
                possible_titles=await _possible_titles(db, series.book_ids, series.titles),
            )
        )
    return gaps


async def dismiss_series_gaps(db: AsyncSession, series_name: str) -> int:
    """Hide the current gaps of one series; a gap that appears later is shown again."""
    key = series_key(series_name)
    dismissed = 0
    for series in await load_tracked_series(db):
        if series.key != key:
            continue
        for index in missing_indexes(series.whole_indexes):
            finding_key = gap_finding_key(series.name, index)
            finding = await db.scalar(select(models.SeriesFinding).where(models.SeriesFinding.finding_key == finding_key))
            if finding is None:
                finding = models.SeriesFinding(
                    kind="gap",
                    finding_key=finding_key,
                    series_name=series.name,
                    author=series.author or None,
                    series_index=Decimal(index),
                    notified_at=datetime.now(timezone.utc),
                )
                db.add(finding)
            if finding.status != "dismissed":
                finding.status = "dismissed"
                dismissed += 1
    await db.commit()
    return dismissed


async def dismiss_series_release(db: AsyncSession, finding_id: int) -> bool:
    finding = await db.get(models.SeriesFinding, finding_id)
    if finding is None or finding.kind != "release":
        return False
    finding.status = "dismissed"
    await db.commit()
    return True


async def sync_series_gaps(db: AsyncSession) -> list[SeriesGap]:
    """Record current gaps and return only those not seen before."""
    tracked = await load_tracked_series(db)
    current: dict[str, tuple[TrackedSeries, int]] = {}
    for series in tracked:
        for index in missing_indexes(series.whole_indexes):
            current[gap_finding_key(series.name, index)] = (series, index)

    existing = {
        finding.finding_key: finding
        for finding in (await db.execute(select(models.SeriesFinding).where(models.SeriesFinding.kind == "gap")))
        .scalars()
        .all()
    }
    for finding_key, finding in existing.items():
        if finding_key not in current:
            # The gap was filled (or the series renumbered); forget it, including any dismissal.
            await db.delete(finding)

    new_by_series: dict[str, SeriesGap] = {}
    now = datetime.now(timezone.utc)
    for finding_key, (series, index) in current.items():
        if finding_key in existing:
            continue
        db.add(
            models.SeriesFinding(
                kind="gap",
                finding_key=finding_key,
                series_name=series.name,
                author=series.author or None,
                series_index=Decimal(index),
                notified_at=now,
            )
        )
        gap = new_by_series.setdefault(
            series.key,
            SeriesGap(series_name=series.name, author=series.author, missing_indexes=[], owned_count=len(series.book_ids)),
        )
        gap.missing_indexes.append(index)
    await db.commit()
    return list(new_by_series.values())


def parse_published_date(value: object) -> tuple[date, date] | None:
    """Return the first and last day a ``YYYY[-MM[-DD]]`` publication date can mean."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split("-")
    try:
        numbers = [int(part) for part in parts]
        if len(numbers) == 1:
            return date(numbers[0], 1, 1), date(numbers[0], 12, 31)
        if len(numbers) == 2:
            last_day = calendar.monthrange(numbers[0], numbers[1])[1]
            return date(numbers[0], numbers[1], 1), date(numbers[0], numbers[1], last_day)
        if len(numbers) == 3:
            exact = date(numbers[0], numbers[1], numbers[2])
            return exact, exact
    except ValueError:
        return None
    return None


def _series_search_text(name: str) -> str:
    normalized = normalize_text(name)
    return normalized[4:] if normalized.startswith("the ") else normalized


def select_release_candidates(
    series: TrackedSeries,
    volumes: list[dict[str, object]],
    *,
    today: date,
) -> list[ReleaseCandidate]:
    """Keep volumes that look like unowned, recent or upcoming books of ``series``."""
    series_text = _series_search_text(series.name)
    candidates: dict[str, ReleaseCandidate] = {}
    for volume in volumes:
        info = volume.get("volumeInfo")
        if not isinstance(info, dict):
            continue
        title = str(info.get("title") or "").strip()
        subtitle = str(info.get("subtitle") or "").strip()
        if not title:
            continue
        period = parse_published_date(info.get("publishedDate"))
        if period is None or period[1] < today - RELEASE_LOOKBACK:
            continue
        authors = info.get("authors")
        author_names = [author for author in authors if isinstance(author, str)] if isinstance(authors, list) else []
        if series.author and best_author_similarity(series.author, author_names) < _AUTHOR_MATCH_THRESHOLD:
            continue
        full_title = f"{title}: {subtitle}" if subtitle else title
        if not series_text or series_text not in normalize_text(full_title):
            continue
        if any(
            max(title_similarity(owned, title), title_similarity(owned, full_title)) >= _OWNED_TITLE_THRESHOLD
            for owned in series.titles
        ):
            continue
        _, series_index = infer_series_metadata(full_title, series.name)
        if series_index is not None and series_index == int(series_index) and int(series_index) in series.whole_indexes:
            continue  # A new edition of a volume already in the library.
        info_link = info.get("infoLink")
        candidate = ReleaseCandidate(
            title=full_title,
            published_date=str(info.get("publishedDate")).strip(),
            release_date=period[0],
            series_index=series_index,
            remote_url=info_link if isinstance(info_link, str) and info_link.startswith("http") else None,
        )
        key = normalize_text(title)
        known = candidates.get(key)
        # Several editions of one book: keep the earliest release.
        if known is None or candidate.release_date < known.release_date:
            candidates[key] = candidate
    return sorted(candidates.values(), key=lambda item: (item.release_date, item.title.casefold()))


def fetch_release_volumes(series: TrackedSeries) -> list[dict[str, object]]:
    """Blocking Google Books search; call through ``asyncio.to_thread``."""
    query = f'"{series.name}"'
    if series.author:
        query = f'inauthor:"{series.author}" {query}'
    payload = request_google_books_json(
        "/volumes",
        params={"q": query, "orderBy": "newest", "printType": "books", "maxResults": 20},
    )
    return [dict(volume) for volume in valid_records(payload, "items", GOOGLE_VOLUME)]


def _owns_index(series: TrackedSeries, index: Decimal | float | None) -> bool:
    """True when ``index`` is a whole volume number already in the library."""
    if index is None:
        return False
    number = float(index)
    return number.is_integer() and int(number) in series.whole_indexes


async def sync_series_releases(
    db: AsyncSession,
    *,
    today: date | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[models.SeriesFinding], int]:
    """Refresh release findings. Returns (newly found releases, series that failed to check)."""
    today = today or datetime.now(timezone.utc).date()
    tracked = await load_tracked_series(db)
    by_key = {series.key: series for series in tracked}

    # Drop releases that are now in the library or whose series is gone.
    existing = list(
        (await db.execute(select(models.SeriesFinding).where(models.SeriesFinding.kind == "release"))).scalars().all()
    )
    remaining: dict[str, models.SeriesFinding] = {}
    for finding in existing:
        owner = by_key.get(series_key(finding.series_name))
        owned = owner is not None and (
            any(title_similarity(owned_title, finding.title or "") >= _OWNED_TITLE_THRESHOLD for owned_title in owner.titles)
            or _owns_index(owner, finding.series_index)
        )
        if owner is None or owned:
            await db.delete(finding)
        else:
            remaining[finding.finding_key] = finding
    await db.commit()

    new_findings: list[models.SeriesFinding] = []
    failures = 0
    if not google_books_enabled():
        return new_findings, failures

    searchable = [series for series in tracked if series.has_published_book and series.author]
    if len(searchable) > MAX_RELEASE_SERIES_PER_RUN:
        logger.info("Checking releases for %d of %d series this run.", MAX_RELEASE_SERIES_PER_RUN, len(searchable))
        # Rotate through a large library a slice per day instead of always the same slice.
        offset = (today.toordinal() * MAX_RELEASE_SERIES_PER_RUN) % len(searchable)
        searchable = (searchable[offset:] + searchable[:offset])[:MAX_RELEASE_SERIES_PER_RUN]

    now = datetime.now(timezone.utc)
    for position, series in enumerate(searchable, start=1):
        if progress is not None:
            await progress(position - 1, len(searchable), f"Checking releases for {series.name}")
        try:
            volumes = await asyncio.to_thread(fetch_release_volumes, series)
        except requests.RequestException:
            logger.warning("Could not check releases for series %s.", series.name)
            failures += 1
            continue
        for candidate in select_release_candidates(series, volumes, today=today):
            finding_key = release_finding_key(series.name, candidate.title)
            release = remaining.get(finding_key)
            index = Decimal(str(candidate.series_index)) if candidate.series_index is not None else None
            if release is None:
                release = models.SeriesFinding(
                    kind="release",
                    finding_key=finding_key,
                    series_name=series.name,
                    author=series.author or None,
                    title=candidate.title,
                    source="google_books",
                    notified_at=now,
                )
                db.add(release)
                remaining[finding_key] = release
                new_findings.append(release)
            release.series_index = index
            release.published_date = candidate.published_date
            release.release_date = candidate.release_date
            release.remote_url = candidate.remote_url
        await db.commit()
    return new_findings, failures


def _format_indexes(indexes: list[int]) -> str:
    return ", ".join(f"#{index}" for index in sorted(indexes))


def series_notification_message(gaps: list[SeriesGap], releases: list[models.SeriesFinding]) -> str:
    lines: list[str] = []
    for release in releases:
        when = f" ({release.published_date})" if release.published_date else ""
        lines.append(f"New release in {release.series_name}: {release.title}{when}")
    for gap in gaps:
        lines.append(f"Missing from {gap.series_name}: {_format_indexes(gap.missing_indexes)}")
    if len(lines) > _NOTIFICATION_LINE_LIMIT:
        hidden = len(lines) - _NOTIFICATION_LINE_LIMIT
        lines = [*lines[:_NOTIFICATION_LINE_LIMIT], f"…and {hidden} more"]
    return "\n".join(lines)


async def run_series_check(progress: ProgressCallback | None = None) -> str:
    """Refresh gap and release findings, announce new ones, and summarize the run."""
    async with SessionLocal() as db:
        new_gaps = await sync_series_gaps(db)
        new_releases, failures = await sync_series_releases(db, progress=progress)
        message = series_notification_message(new_gaps, new_releases)
        release_count = len(new_releases)
    gap_count = sum(len(gap.missing_indexes) for gap in new_gaps)
    if message:
        await emit_notification(EVENT_SERIES_UPDATE, "Series updates", message)
    detail = f"Series check found {gap_count} new gap(s) and {release_count} new release(s)"
    if not google_books_enabled():
        detail += "; release lookups are off because Google Books is disabled"
    elif failures:
        detail += f"; {failures} series could not be checked"
    return detail
