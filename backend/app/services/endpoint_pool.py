"""Ordered AI endpoint pools with lightweight failure cooldowns."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Generic, TypeVar

from ..models import AudiobookSettings

COOLDOWN_SECONDS = 60.0

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class RoutedResult(Generic[T]):
    value: T
    endpoint: dict[str, Any]


_cooldowns: dict[tuple[str, str], float] = {}


def _legacy_endpoint(settings: AudiobookSettings, capability: str) -> dict[str, Any]:
    prefix = "transcription" if capability == "transcription" else capability
    provider_default = {"llm": "stub", "tts": "stub", "transcription": "none"}[capability]
    endpoint: dict[str, Any] = {
        "id": f"legacy-{capability}",
        "name": "Primary",
        "provider": getattr(settings, f"{prefix}_provider", None) or provider_default,
        "api_key": getattr(settings, f"{prefix}_api_key", None),
        "base_url": getattr(settings, f"{prefix}_base_url", None),
        "model": getattr(settings, f"{prefix}_model", None),
    }
    if capability == "tts":
        endpoint["default_voice"] = settings.tts_default_voice
    if capability == "transcription":
        endpoint["language"] = settings.transcription_language
    return endpoint


def configured_endpoints(settings: AudiobookSettings | None, capability: str) -> list[dict[str, Any]]:
    """Return endpoints in priority order, falling back to legacy columns."""
    if settings is None:
        return []
    field = f"{capability}_endpoints"
    stored = getattr(settings, field, None)
    if stored is None:
        return [_legacy_endpoint(settings, capability)]
    return [dict(endpoint) for endpoint in stored if isinstance(endpoint, dict)]


def primary_provider(settings: AudiobookSettings | None, capability: str, default: str) -> str:
    endpoints = configured_endpoints(settings, capability)
    provider = endpoints[0].get("provider") if endpoints else default
    return str(provider or default).strip().lower()


def _endpoint_key(capability: str, endpoint: dict[str, Any]) -> tuple[str, str]:
    identity = endpoint.get("id") or "|".join(
        str(endpoint.get(field) or "") for field in ("name", "provider", "base_url", "model")
    )
    return capability, str(identity)


def _endpoint_settings(
    settings: AudiobookSettings,
    capability: str,
    endpoint: dict[str, Any],
) -> SimpleNamespace:
    """Expose one generic endpoint through the legacy provider field names."""
    values = {column.name: getattr(settings, column.name) for column in settings.__table__.columns}
    prefix = "transcription" if capability == "transcription" else capability
    for field in ("provider", "api_key", "base_url", "model"):
        values[f"{prefix}_{field}"] = endpoint.get(field)
    if capability == "tts":
        values["tts_default_voice"] = endpoint.get("default_voice")
    elif capability == "transcription":
        values["transcription_language"] = endpoint.get("language")
    return SimpleNamespace(**values)


def cooldown_remaining(capability: str, endpoint: dict[str, Any]) -> float:
    remaining = _cooldowns.get(_endpoint_key(capability, endpoint), 0.0) - time.monotonic()
    return max(0.0, remaining)


async def route_request(
    settings: AudiobookSettings,
    capability: str,
    attempt: Callable[[Any], Awaitable[T]],
) -> RoutedResult[T]:
    """Try available endpoints in priority order and cool failed hosts down."""
    endpoints = configured_endpoints(settings, capability)
    if not endpoints:
        raise RuntimeError(f"No {capability} endpoints are configured in Audio & AI Configuration.")

    available = [endpoint for endpoint in endpoints if cooldown_remaining(capability, endpoint) <= 0]
    if not available:
        wait_seconds = min(cooldown_remaining(capability, endpoint) for endpoint in endpoints)
        raise RuntimeError(
            f"All {capability} endpoints are cooling down after failures; retry in {max(1, round(wait_seconds))} seconds."
        )

    last_error: Exception | None = None
    for endpoint in available:
        key = _endpoint_key(capability, endpoint)
        started_at = time.perf_counter()
        try:
            value = await attempt(_endpoint_settings(settings, capability, endpoint))
        except Exception as exc:
            await _record_endpoint_attempt(
                settings,
                capability,
                endpoint,
                success=False,
                duration_ms=(time.perf_counter() - started_at) * 1000,
                error_type=type(exc).__name__,
            )
            _cooldowns[key] = time.monotonic() + COOLDOWN_SECONDS
            logger.warning(
                "%s endpoint %r failed and will cool down for %.0f seconds: %s",
                capability.upper(),
                endpoint.get("name") or endpoint.get("base_url") or endpoint.get("id"),
                COOLDOWN_SECONDS,
                exc,
            )
            last_error = exc
            continue
        await _record_endpoint_attempt(
            settings,
            capability,
            endpoint,
            success=True,
            duration_ms=(time.perf_counter() - started_at) * 1000,
        )
        _cooldowns.pop(key, None)
        return RoutedResult(value=value, endpoint=endpoint)

    assert last_error is not None
    raise last_error


async def _record_endpoint_attempt(
    settings: AudiobookSettings,
    capability: str,
    endpoint: dict[str, Any],
    **measurement: Any,
) -> None:
    """Keep observability failures from affecting the routed AI request."""
    if settings.id is None:
        return
    try:
        from .endpoint_metrics import record_attempt

        await record_attempt(settings.id, capability, endpoint, **measurement)
    except Exception:
        logger.exception("Failed to record %s endpoint request metric", capability.upper())


def reset_cooldowns() -> None:
    """Clear process-local cooldown state (primarily useful for tests)."""
    _cooldowns.clear()
