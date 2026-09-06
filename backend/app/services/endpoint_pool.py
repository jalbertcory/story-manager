"""Ordered AI endpoint pools with lightweight failure cooldowns."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Generic, TypeVar

from ..models import AudiobookSettings


class EndpointSettings(SimpleNamespace):
    """Typed projection of persisted settings for one provider or endpoint."""

    id: int
    llm_provider: str | None
    llm_api_key: str | None
    llm_base_url: str | None
    llm_model: str | None
    tts_provider: str | None
    tts_api_key: str | None
    tts_base_url: str | None
    tts_model: str | None
    tts_default_voice: str | None
    tts_max_block_chars: int
    tts_voice_similarity_threshold: float
    tts_quality_attempts: int
    transcription_provider: str | None
    transcription_api_key: str | None
    transcription_base_url: str | None
    transcription_model: str | None
    transcription_language: str | None
    llm_endpoints: list[dict[str, Any]] | None
    tts_endpoints: list[dict[str, Any]] | None
    transcription_endpoints: list[dict[str, Any]] | None
    roster_prompt_template: str | None
    diarization_prompt_template: str | None


ProviderSettings = AudiobookSettings | EndpointSettings


COOLDOWN_SECONDS = 60.0

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class RoutedResult(Generic[T]):
    value: T
    endpoint: dict[str, Any]


@dataclass(frozen=True)
class EndpointProbeResult(Generic[T]):
    """The outcome of directly testing one configured endpoint."""

    endpoint: dict[str, Any]
    success: bool
    duration_ms: float
    value: T | None = None
    error: str | None = None


_cooldowns: dict[tuple[str, str], float] = {}


def _legacy_endpoint(settings: ProviderSettings, capability: str) -> dict[str, Any]:
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


def configured_endpoints(settings: ProviderSettings | None, capability: str) -> list[dict[str, Any]]:
    """Return endpoints in priority order, falling back to legacy columns."""
    if settings is None:
        return []
    field = f"{capability}_endpoints"
    stored = getattr(settings, field, None)
    if stored is None:
        return [_legacy_endpoint(settings, capability)]
    return [dict(endpoint) for endpoint in stored if isinstance(endpoint, dict)]


def configured_providers(settings: ProviderSettings | None, capability: str) -> list[str]:
    """Return unique configured providers in endpoint priority order."""
    return list(
        dict.fromkeys(
            str(endpoint.get("provider") or "").strip().lower()
            for endpoint in configured_endpoints(settings, capability)
            if str(endpoint.get("provider") or "").strip()
        )
    )


def settings_for_provider(
    settings: AudiobookSettings,
    capability: str,
    provider: str,
) -> EndpointSettings:
    """Restrict routing to endpoints owned by one persisted provider."""
    normalized = provider.strip().lower()
    endpoints = [
        endpoint
        for endpoint in configured_endpoints(settings, capability)
        if str(endpoint.get("provider") or "").strip().lower() == normalized
    ]
    if not endpoints:
        raise RuntimeError(
            f"This audiobook is locked to {normalized}, but no {normalized} {capability.upper()} endpoint is configured."
        )
    values = {column.name: getattr(settings, column.name) for column in settings.__table__.columns}
    values[f"{capability}_endpoints"] = endpoints
    prefix = "transcription" if capability == "transcription" else capability
    primary = endpoints[0]
    for field in ("provider", "api_key", "base_url", "model"):
        values[f"{prefix}_{field}"] = primary.get(field)
    if capability == "tts":
        values["tts_default_voice"] = primary.get("default_voice")
    elif capability == "transcription":
        values["transcription_language"] = primary.get("language")
    return EndpointSettings(**values)


def primary_provider(settings: ProviderSettings | None, capability: str, default: str) -> str:
    endpoints = configured_endpoints(settings, capability)
    provider = endpoints[0].get("provider") if endpoints else default
    return str(provider or default).strip().lower()


def _endpoint_key(capability: str, endpoint: dict[str, Any]) -> tuple[str, str]:
    identity = endpoint.get("id") or "|".join(
        str(endpoint.get(field) or "") for field in ("name", "provider", "base_url", "model")
    )
    return capability, str(identity)


def _endpoint_settings(
    settings: ProviderSettings,
    capability: str,
    endpoint: dict[str, Any],
) -> EndpointSettings:
    """Expose one generic endpoint through the legacy provider field names."""
    if hasattr(settings, "__table__"):
        values = {column.name: getattr(settings, column.name) for column in settings.__table__.columns}
    else:
        values = dict(vars(settings))
    prefix = "transcription" if capability == "transcription" else capability
    for field in ("provider", "api_key", "base_url", "model"):
        values[f"{prefix}_{field}"] = endpoint.get(field)
    if capability == "tts":
        values["tts_default_voice"] = endpoint.get("default_voice")
    elif capability == "transcription":
        values["transcription_language"] = endpoint.get("language")
    return EndpointSettings(**values)


def cooldown_remaining(capability: str, endpoint: dict[str, Any]) -> float:
    remaining = _cooldowns.get(_endpoint_key(capability, endpoint), 0.0) - time.monotonic()
    return max(0.0, remaining)


def _error_detail(exc: Exception) -> str:
    """Include a provider response detail without dumping a large response body."""
    message = str(exc).strip() or type(exc).__name__
    response = getattr(exc, "response", None)
    detail: Any = None
    if response is not None:
        try:
            payload = response.json()
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("message") or payload.get("error")
            if isinstance(detail, dict):
                detail = detail.get("message") or str(detail)
        if not detail:
            try:
                detail = response.text
            except Exception:
                detail = None
    if detail:
        normalized = " ".join(str(detail).split())
        if normalized and normalized not in message:
            message = f"{message} — {normalized}"
    return message[:1000]


async def probe_endpoints(
    settings: ProviderSettings,
    capability: str,
    attempt: Callable[[EndpointSettings], Awaitable[T]],
) -> list[EndpointProbeResult[T]]:
    """Test every endpoint, including endpoints currently in cooldown."""
    results: list[EndpointProbeResult[T]] = []
    for endpoint in configured_endpoints(settings, capability):
        key = _endpoint_key(capability, endpoint)
        started_at = time.perf_counter()
        try:
            value = await attempt(_endpoint_settings(settings, capability, endpoint))
        except Exception as exc:
            duration_ms = (time.perf_counter() - started_at) * 1000
            await _record_endpoint_attempt(
                settings,
                capability,
                endpoint,
                success=False,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
            )
            _cooldowns[key] = time.monotonic() + COOLDOWN_SECONDS
            results.append(
                EndpointProbeResult(
                    endpoint=endpoint,
                    success=False,
                    duration_ms=duration_ms,
                    error=_error_detail(exc),
                )
            )
            continue
        duration_ms = (time.perf_counter() - started_at) * 1000
        await _record_endpoint_attempt(
            settings,
            capability,
            endpoint,
            success=True,
            duration_ms=duration_ms,
        )
        _cooldowns.pop(key, None)
        results.append(
            EndpointProbeResult(
                endpoint=endpoint,
                success=True,
                duration_ms=duration_ms,
                value=value,
            )
        )
    return results


async def route_request(
    settings: ProviderSettings,
    capability: str,
    attempt: Callable[[EndpointSettings], Awaitable[T]],
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
    settings: ProviderSettings,
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


def reset_cooldowns(capability: str | None = None) -> None:
    """Clear process-local cooldown state, optionally for one capability."""
    if capability is None:
        _cooldowns.clear()
        return
    for key in [key for key in _cooldowns if key[0] == capability]:
        _cooldowns.pop(key, None)
