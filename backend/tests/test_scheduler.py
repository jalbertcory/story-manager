"""Tests for scheduler logic: next run calculation, last run anchor."""

from datetime import datetime, timedelta, timezone

from backend.app.services.update_scheduler import (
    OVERDUE_RUN_DELAY,
    WEB_NOVEL_UPDATE_INTERVAL,
    calculate_next_run_time,
    get_last_run_anchor,
)


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
