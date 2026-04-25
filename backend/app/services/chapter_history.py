"""Chapter update history summaries for web books."""

from datetime import datetime, timedelta, timezone

from .. import models, schemas

WORDS_PER_MONTH_WEEKS = 52 / 12
CATCH_UP_SYNC_MIN_CHAPTERS = 5
CATCH_UP_SYNC_MIN_WORDS = 20_000


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _chapter_delta(log: models.BookLog) -> int:
    if log.previous_chapter_count is None or log.new_chapter_count is None:
        return 0
    return max(log.new_chapter_count - log.previous_chapter_count, 0)


def _is_chapter_growth_log(log: models.BookLog) -> bool:
    return (
        log.entry_type == "updated"
        and log.previous_chapter_count is not None
        and log.previous_chapter_count > 0
        and _chapter_delta(log) > 0
    )


def _is_initial_sync_log(log: models.BookLog) -> bool:
    return log.entry_type == "added" and (log.new_chapter_count or 0) > 0


def build_chapter_update_history(
    book_id: int,
    logs: list[models.BookLog],
    now: datetime | None = None,
) -> schemas.BookChapterUpdateHistory:
    points: list[schemas.BookChapterUpdateHistoryPoint] = []
    seen_initial_sync = False
    seen_post_initial_growth = False
    for log in logs:
        is_initial_sync = _is_initial_sync_log(log)
        included_in_stats = _is_chapter_growth_log(log)
        if not is_initial_sync and not included_in_stats:
            continue
        chapters_added = (log.new_chapter_count or 0) if is_initial_sync else _chapter_delta(log)
        words_added = max(log.words_added or 0, 0)
        is_catch_up_sync = (
            included_in_stats
            and seen_initial_sync
            and not seen_post_initial_growth
            and (chapters_added >= CATCH_UP_SYNC_MIN_CHAPTERS or words_added >= CATCH_UP_SYNC_MIN_WORDS)
        )
        included_in_stats = included_in_stats and not is_catch_up_sync
        points.append(
            schemas.BookChapterUpdateHistoryPoint(
                id=log.id,
                timestamp=log.timestamp,
                entry_type=log.entry_type,
                previous_chapter_count=log.previous_chapter_count,
                new_chapter_count=log.new_chapter_count,
                chapters_added=chapters_added,
                words_added=words_added,
                average_words_per_chapter=words_added / chapters_added if chapters_added else None,
                included_in_stats=included_in_stats,
                is_initial_sync=is_initial_sync,
                is_catch_up_sync=is_catch_up_sync,
            )
        )
        if is_initial_sync:
            seen_initial_sync = True
        elif _is_chapter_growth_log(log):
            seen_post_initial_growth = True

    stats_points = [point for point in points if point.included_in_stats]
    total_words_added = sum(point.words_added for point in stats_points)
    total_chapters_added = sum(point.chapters_added for point in stats_points)
    average_words_per_week = None
    average_words_per_month = None
    average_days_between_updates = None
    predicted_next_update_at = None
    last_update_at = stats_points[-1].timestamp if stats_points else None

    if stats_points:
        now_utc = _as_utc(now or datetime.now(timezone.utc))
        first_update_at = _as_utc(stats_points[0].timestamp)
        elapsed_days = max((now_utc - first_update_at).total_seconds() / 86400, 1)
        average_words_per_week = total_words_added / (elapsed_days / 7)
        average_words_per_month = average_words_per_week * WORDS_PER_MONTH_WEEKS

    if len(stats_points) >= 2:
        timestamps = [_as_utc(point.timestamp) for point in stats_points]
        intervals = [(current - previous).total_seconds() / 86400 for previous, current in zip(timestamps, timestamps[1:])]
        average_days_between_updates = sum(intervals) / len(intervals)
        predicted_next_update_at = timestamps[-1] + timedelta(days=average_days_between_updates)

    return schemas.BookChapterUpdateHistory(
        book_id=book_id,
        history=points,
        summary=schemas.BookChapterUpdateHistorySummary(
            total_update_events=len(stats_points),
            total_chapters_added=total_chapters_added,
            total_words_added=total_words_added,
            average_words_per_week=average_words_per_week,
            average_words_per_month=average_words_per_month,
            average_days_between_updates=average_days_between_updates,
            predicted_next_update_at=predicted_next_update_at,
            last_update_at=last_update_at,
        ),
    )
