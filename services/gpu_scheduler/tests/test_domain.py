from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from services.gpu_scheduler.domain import SchedulerConfig, TimeWindow, effective_availability, schedule_is_active


def at_utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def config_for(day: str, start: str, end: str) -> SchedulerConfig:
    return SchedulerConfig(enabled=True, timezone="UTC", schedule={day: [TimeWindow(start=start, end=end)]})


def test_daytime_window_is_end_exclusive():
    config = config_for("monday", "09:00", "17:00")

    assert schedule_is_active(config, at_utc(2026, 8, 3, 9)) is True
    assert schedule_is_active(config, at_utc(2026, 8, 3, 16, 59)) is True
    assert schedule_is_active(config, at_utc(2026, 8, 3, 17)) is False


def test_overnight_window_continues_into_following_day():
    config = config_for("friday", "20:00", "02:00")

    assert schedule_is_active(config, at_utc(2026, 8, 7, 23)) is True
    assert schedule_is_active(config, at_utc(2026, 8, 8, 1, 59)) is True
    assert schedule_is_active(config, at_utc(2026, 8, 8, 2)) is False


def test_equal_times_mean_all_day():
    config = config_for("sunday", "00:00", "00:00")

    assert schedule_is_active(config, at_utc(2026, 8, 9, 0)) is True
    assert schedule_is_active(config, at_utc(2026, 8, 9, 23, 59)) is True


def test_disabled_configuration_is_observe_only():
    desired, source = effective_availability(SchedulerConfig(enabled=False), at_utc(2026, 8, 3, 12))

    assert desired is None
    assert source == "disabled"


def test_override_wins_over_schedule_until_expiration():
    config = config_for("monday", "09:00", "17:00")
    config.override_mode = "unavailable"
    config.override_until = at_utc(2026, 8, 3, 13)

    assert effective_availability(config, at_utc(2026, 8, 3, 12)) == (False, "override")
    assert effective_availability(config, at_utc(2026, 8, 3, 14)) == (True, "schedule")


def test_invalid_time_and_timezone_are_rejected():
    with pytest.raises(ValidationError):
        TimeWindow(start="9:00", end="17:00")
    with pytest.raises(ValidationError):
        SchedulerConfig(timezone="Somewhere/Imaginary")
