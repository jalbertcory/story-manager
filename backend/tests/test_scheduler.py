"""Tests for scheduler logic: next run calculation, last run anchor."""

from datetime import datetime, timezone

from backend.app.services.update_scheduler import (
    OVERDUE_RUN_DELAY,
    WEB_NOVEL_UPDATE_INTERVAL,
    calculate_next_daily_run_time,
    calculate_next_run_time,
    get_last_run_anchor,
    get_next_run_time_for_task,
    get_schedule_label,
)
from backend.app import models


def _utc(year=2025, month=1, day=1, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class TestCalculateNextRunTime:
    def test_no_previous_run(self):
        """First run should be scheduled one interval from now."""
        now = _utc()
        result = calculate_next_run_time(None, now=now)
        assert result == now + WEB_NOVEL_UPDATE_INTERVAL

    def test_normal_interval(self):
        """After a run, the next should be one interval later."""
        last_run = _utc(hour=6)
        now = _utc(hour=12)
        result = calculate_next_run_time(last_run, now=now)
        expected = last_run + WEB_NOVEL_UPDATE_INTERVAL
        assert result == expected

    def test_overdue_run(self):
        """If the next run is already past, schedule with a small delay."""
        last_run = _utc(year=2024, month=12, day=30)  # >24h ago
        now = _utc(year=2025, month=1, day=2)
        result = calculate_next_run_time(last_run, now=now)
        assert result == now + OVERDUE_RUN_DELAY

    def test_exactly_at_interval(self):
        """If exactly at interval boundary, should be overdue."""
        last_run = _utc(hour=0)
        now = last_run + WEB_NOVEL_UPDATE_INTERVAL
        result = calculate_next_run_time(last_run, now=now)
        assert result == now + OVERDUE_RUN_DELAY

    def test_naive_datetime_treated_as_utc(self):
        """Naive datetimes (no tz) should be treated as UTC."""
        naive_last = datetime(2025, 1, 1, 12, 0)
        now = _utc(hour=14)
        result = calculate_next_run_time(naive_last, now=now)
        expected = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
        assert result == expected


class TestGetLastRunAnchor:
    def test_none_task(self):
        assert get_last_run_anchor(None) is None

    def test_completed_task_uses_completed_at(self):
        class FakeTask:
            status = "completed"
            started_at = _utc(hour=10)
            completed_at = _utc(hour=11)

        result = get_last_run_anchor(FakeTask())
        assert result == _utc(hour=11)

    def test_running_task_uses_started_at(self):
        class FakeTask:
            status = "running"
            started_at = _utc(hour=10)
            completed_at = None

        result = get_last_run_anchor(FakeTask())
        assert result == _utc(hour=10)

    def test_failed_task_uses_started_at(self):
        class FakeTask:
            status = "failed"
            started_at = _utc(hour=10)
            completed_at = None

        result = get_last_run_anchor(FakeTask())
        assert result == _utc(hour=10)


class TestGetNextRunTimeForTask:
    def test_interrupted_incomplete_task_retries_soon(self):
        class FakeTask:
            status = "interrupted"
            started_at = _utc(hour=10)
            completed_at = _utc(hour=10, minute=15)
            completed_books = 14
            total_books = 30

        now = _utc(hour=10, minute=16)
        result = get_next_run_time_for_task(FakeTask(), now=now)
        assert result == now + OVERDUE_RUN_DELAY

    def test_completed_task_uses_normal_interval(self):
        class FakeTask:
            status = "completed"
            started_at = _utc(hour=10)
            completed_at = _utc(hour=11)
            completed_books = 30
            total_books = 30

        now = _utc(hour=12)
        result = get_next_run_time_for_task(FakeTask(), now=now)
        assert result == _utc(year=2025, month=1, day=2, hour=11)

    def test_daily_schedule_uses_fixed_local_time(self):
        class FakeTask:
            status = "completed"
            started_at = _utc(hour=6)
            completed_at = _utc(hour=7)
            completed_books = 30
            total_books = 30

        settings = models.SchedulerSettings(
            web_novel_schedule_hour=6,
            web_novel_schedule_minute=30,
            web_novel_schedule_timezone="America/New_York",
        )
        now = _utc(year=2025, month=1, day=1, hour=12)
        result = get_next_run_time_for_task(FakeTask(), schedule_settings=settings, now=now)
        assert result == _utc(year=2025, month=1, day=2, hour=11, minute=30)


class TestDailyScheduleHelpers:
    def test_calculate_next_daily_run_time(self):
        now = _utc(year=2025, month=1, day=1, hour=12)
        result = calculate_next_daily_run_time(6, 30, "America/New_York", now=now)
        assert result == _utc(year=2025, month=1, day=2, hour=11, minute=30)

    def test_get_schedule_label_for_daily_time(self):
        settings = models.SchedulerSettings(
            web_novel_schedule_hour=6,
            web_novel_schedule_minute=30,
            web_novel_schedule_timezone="America/New_York",
        )
        assert get_schedule_label(settings) == "Daily at 6:30 AM (America/New_York)"
