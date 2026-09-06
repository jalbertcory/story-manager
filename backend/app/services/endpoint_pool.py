"""Ordered AI endpoint pools with lightweight failure cooldowns."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field, field_validator, ValidationInfo
from typing import Any, Awaitable, Callable, Generic, TypeVar

from ..models import AudiobookSettings
from ..endpoint_types import EndpointConfig


class EndpointSettings(BaseModel):
    """Validated projection of persisted settings for one provider or endpoint."""

    model_config = ConfigDict(from_attributes=True, hide_input_in_errors=True)

    id: int | None = None
    llm_provider: str | None = None
    llm_api_key: str | None = Field(default=None, repr=False)
    llm_base_url: str | None = None
    llm_model: str | None = None
    tts_provider: str | None = None
    tts_api_key: str | None = Field(default=None, repr=False)
    tts_base_url: str | None = None
    tts_model: str | None = None
    tts_default_voice: str | None = None
    tts_max_block_chars: int = 500
    tts_voice_similarity_threshold: float = 0.45
    tts_quality_attempts: int = 3
    transcription_provider: str | None = None
    transcription_api_key: str | None = Field(default=None, repr=False)
    transcription_base_url: str | None = None
    transcription_model: str | None = None
    transcription_language: str | None = None
    llm_endpoints: list[EndpointConfig] | None = None
    tts_endpoints: list[EndpointConfig] | None = None
    transcription_endpoints: list[EndpointConfig] | None = None
    roster_prompt_template: str | None = None
    diarization_prompt_template: str | None = None

    @field_validator("tts_max_block_chars", "tts_voice_similarity_threshold", "tts_quality_attempts", mode="before")
    @classmethod
    def legacy_numeric_defaults(cls, value: object, info: ValidationInfo) -> object:
        return cls.model_fields[info.field_name].default if value is None and info.field_name else value


ProviderSettings = AudiobookSettings | EndpointSettings


COOLDOWN_SECONDS = 60.0

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class RoutedResult(Generic[T]):
    value: T
    endpoint: EndpointConfig


@dataclass(frozen=True)
class EndpointProbeResult(Generic[T]):
    """The outcome of directly testing one configured endpoint."""

    endpoint: EndpointConfig
    success: bool
    duration_ms: float
    value: T | None = None
    error: str | None = None


_cooldowns: dict[tuple[str, str], float] = {}


def _legacy_endpoint(settings: EndpointSettings, capability: str) -> EndpointConfig:
    if capability == "llm":
        return EndpointConfig(
            id="legacy-llm",
            name="Primary",
            provider=settings.llm_provider or "stub",
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )
    if capability == "tts":
        return EndpointConfig(
            id="legacy-tts",
            name="Primary",
            provider=settings.tts_provider or "stub",
            api_key=settings.tts_api_key,
            base_url=settings.tts_base_url,
            model=settings.tts_model,
            default_voice=settings.tts_default_voice,
        )
    if capability == "transcription":
        return EndpointConfig(
            id="legacy-transcription",
            name="Primary",
            provider=settings.transcription_provider or "none",
            api_key=settings.transcription_api_key,
            base_url=settings.transcription_base_url,
            model=settings.transcription_model,
            language=settings.transcription_language,
        )
    raise ValueError(f"Unknown endpoint capability: {capability}")


def configured_endpoints(settings: ProviderSettings | None, capability: str) -> list[EndpointConfig]:
    """Validate stored pools and fall back to primary columns for legacy records."""
    if settings is None:
        return []
    projection = EndpointSettings.model_validate(settings)
    if capability == "llm":
        stored = projection.llm_endpoints
    elif capability == "tts":
        stored = projection.tts_endpoints
    elif capability == "transcription":
        stored = projection.transcription_endpoints
    else:
        raise ValueError(f"Unknown endpoint capability: {capability}")
    return stored if stored is not None else [_legacy_endpoint(projection, capability)]


def configured_providers(settings: ProviderSettings | None, capability: str) -> list[str]:
    return list(
        dict.fromkeys(endpoint.provider for endpoint in configured_endpoints(settings, capability) if endpoint.provider)
    )


def settings_for_provider(settings: AudiobookSettings, capability: str, provider: str) -> EndpointSettings:
    normalized = provider.strip().lower()
    endpoints = [endpoint for endpoint in configured_endpoints(settings, capability) if endpoint.provider == normalized]
    if not endpoints:
        raise RuntimeError(
            f"This audiobook is locked to {normalized}, but no {normalized} {capability.upper()} endpoint is configured."
        )
    result = _endpoint_settings(settings, capability, endpoints[0])
    if capability == "llm":
        result.llm_endpoints = endpoints
    elif capability == "tts":
        result.tts_endpoints = endpoints
    elif capability == "transcription":
        result.transcription_endpoints = endpoints
    return result


def primary_provider(settings: ProviderSettings | None, capability: str, default: str) -> str:
    endpoints = configured_endpoints(settings, capability)
    return (endpoints[0].provider if endpoints else default) or default


def _endpoint_key(capability: str, endpoint: EndpointConfig) -> tuple[str, str]:
    identity = endpoint.id or "|".join(
        value or "" for value in (endpoint.name, endpoint.provider, endpoint.base_url, endpoint.model)
    )
    return capability, identity


def _endpoint_settings(settings: ProviderSettings, capability: str, endpoint: EndpointConfig) -> EndpointSettings:
    result = EndpointSettings.model_validate(settings).model_copy(deep=True)
    if capability == "llm":
        result.llm_provider, result.llm_api_key = endpoint.provider, endpoint.api_key
        result.llm_base_url, result.llm_model = endpoint.base_url, endpoint.model
    elif capability == "tts":
        result.tts_provider, result.tts_api_key = endpoint.provider, endpoint.api_key
        result.tts_base_url, result.tts_model = endpoint.base_url, endpoint.model
        result.tts_default_voice = endpoint.default_voice
    elif capability == "transcription":
        result.transcription_provider, result.transcription_api_key = endpoint.provider, endpoint.api_key
        result.transcription_base_url, result.transcription_model = endpoint.base_url, endpoint.model
        result.transcription_language = endpoint.language
    else:
        raise ValueError(f"Unknown endpoint capability: {capability}")
    return result


def cooldown_remaining(capability: str, endpoint: EndpointConfig) -> float:
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
                endpoint.name or endpoint.base_url or endpoint.id,
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
    endpoint: EndpointConfig,
    *,
    success: bool,
    duration_ms: float,
    error_type: str | None = None,
) -> None:
    """Keep observability failures from affecting the routed AI request."""
    if settings.id is None:
        return
    try:
        from .endpoint_metrics import record_attempt

        await record_attempt(
            settings.id, capability, endpoint, success=success, duration_ms=duration_ms, error_type=error_type
        )
    except Exception:
        logger.exception("Failed to record %s endpoint request metric", capability.upper())


def reset_cooldowns(capability: str | None = None) -> None:
    """Clear process-local cooldown state, optionally for one capability."""
    if capability is None:
        _cooldowns.clear()
        return
    for key in [key for key in _cooldowns if key[0] == capability]:
        _cooldowns.pop(key, None)
