"""Configuration models and deterministic schedule evaluation."""

from __future__ import annotations

from datetime import datetime, timedelta
import os
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _default_timezone() -> str:
    candidate = os.getenv("SCHEDULER_TIMEZONE") or os.getenv("TZ") or "UTC"
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError:
        return "UTC"
    return candidate


class TimeWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def valid_time(cls, value: str) -> str:
        if not TIME_PATTERN.fullmatch(value):
            raise ValueError("Time must use 24-hour HH:MM format.")
        return value


def _default_schedule() -> dict[str, list[TimeWindow]]:
    return {day: [] for day in DAY_NAMES}


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    timezone: str = Field(default_factory=_default_timezone)
    schedule: dict[str, list[TimeWindow]] = Field(default_factory=_default_schedule)
    stop_timeout_seconds: int = Field(default=10, ge=1, le=120)
    override_mode: Literal["automatic", "available", "unavailable"] = "automatic"
    override_until: datetime | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown IANA timezone: {value}") from exc
        return value

    @field_validator("schedule")
    @classmethod
    def valid_schedule_days(cls, value: dict[str, list[TimeWindow]]) -> dict[str, list[TimeWindow]]:
        unknown = set(value) - set(DAY_NAMES)
        if unknown:
            raise ValueError(f"Unknown schedule day(s): {', '.join(sorted(unknown))}")
        return {day: list(value.get(day, [])) for day in DAY_NAMES}


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["automatic", "available", "unavailable"]
    duration_minutes: int | None = Field(default=None, ge=1, le=7 * 24 * 60)


def _minute_of_day(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _window_matches(minute: int, start: int, end: int, *, current_day: bool) -> bool:
    if start == end:
        return current_day
    if end > start:
        return current_day and start <= minute < end
    if current_day:
        return minute >= start
    return minute < end


def schedule_is_active(config: SchedulerConfig, now: datetime) -> bool:
    """Return whether ``now`` falls in any configured local-time window.

    Equal start and end times mean all day. Windows whose end precedes their
    start continue into the following day.
    """
    local = now.astimezone(ZoneInfo(config.timezone))
    minute = local.hour * 60 + local.minute
    day_index = local.weekday()

    for window in config.schedule[DAY_NAMES[day_index]]:
        if _window_matches(minute, _minute_of_day(window.start), _minute_of_day(window.end), current_day=True):
            return True

    previous_day = DAY_NAMES[(day_index - 1) % len(DAY_NAMES)]
    for window in config.schedule[previous_day]:
        start = _minute_of_day(window.start)
        end = _minute_of_day(window.end)
        if end < start and _window_matches(minute, start, end, current_day=False):
            return True
    return False


def effective_availability(config: SchedulerConfig, now: datetime) -> tuple[bool | None, str]:
    """Return desired availability and the policy source.

    ``None`` means observe-only mode: the controller reports container state but
    does not start or stop anything.
    """
    if config.override_mode != "automatic":
        if config.override_until is None or now < config.override_until:
            return config.override_mode == "available", "override"
    if not config.enabled:
        return None, "disabled"
    return schedule_is_active(config, now), "schedule"


def next_policy_transition(config: SchedulerConfig, now: datetime) -> datetime | None:
    """Find the next minute at which the effective desired state may change."""
    desired, source = effective_availability(config, now)
    if source == "override" and config.override_until is not None:
        return config.override_until
    if desired is None:
        return None

    candidate = now.replace(second=0, microsecond=0)
    for minute_offset in range(1, 8 * 24 * 60 + 1):
        probe = candidate + timedelta(minutes=minute_offset)
        if schedule_is_active(config, probe) != desired:
            return probe
    return None
