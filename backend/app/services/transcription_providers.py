"""Clients for timestamped speech-to-text services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from pydantic import JsonValue, ValidationError

import httpx

from .media_responses import TranscriptionResponse, TranscriptionHealth

from .endpoint_pool import ProviderSettings, primary_provider, route_request

SUPPORTED_TRANSCRIPTION_PROVIDERS = {"none", "whisperx"}


@dataclass(frozen=True)
class TranscriptWord:
    text: str
    start_ms: int
    end_ms: int
    score: float


@dataclass(frozen=True)
class TranscriptResult:
    language: str | None
    duration_ms: int
    words: list[TranscriptWord]


def transcription_provider_name(settings: ProviderSettings | None) -> str:
    provider = primary_provider(settings, "transcription", "none")
    if provider not in SUPPORTED_TRANSCRIPTION_PROVIDERS:
        choices = ", ".join(sorted(SUPPORTED_TRANSCRIPTION_PROVIDERS))
        raise RuntimeError(f"Unsupported transcription provider {provider!r}. Choose one of: {choices}.")
    return provider


def _service_root(settings: ProviderSettings) -> str:
    if not settings.transcription_base_url:
        raise RuntimeError("Transcription service base URL is required in Audio Settings.")
    root = settings.transcription_base_url.rstrip("/")
    if root.endswith("/transcribe"):
        root = root[: -len("/transcribe")]
    return root


def _headers(settings: ProviderSettings) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if settings.transcription_api_key:
        headers["Authorization"] = f"Bearer {settings.transcription_api_key}"
    return headers


def _raise_for_status(response: httpx.Response, action: str) -> None:
    """Preserve the service's actionable error instead of only exposing an HTTP status."""
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if detail:
            raise RuntimeError(f"Transcription service {action} failed: {detail}") from exc
        raise


async def _transcription_service_health_endpoint(settings: ProviderSettings) -> dict[str, JsonValue]:
    if transcription_provider_name(settings) == "none":
        raise RuntimeError("Configure a transcription provider first.")
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{_service_root(settings)}/health", headers=_headers(settings))
        _raise_for_status(response, "health check")
        payload = response.json()
    try:
        health = TranscriptionHealth.model_validate(payload)
    except ValidationError as exc:
        raise RuntimeError("Transcription service returned an invalid health response.") from exc
    if health.status != "ready":
        raise RuntimeError(f"Transcription service is not ready: {health.status}.")
    configured_model = settings.transcription_model
    loaded_model = health.model
    if configured_model and loaded_model and configured_model != loaded_model:
        raise RuntimeError(
            f"Transcription model mismatch: the service has {loaded_model!r} loaded, "
            f"but Audio Settings request {configured_model!r}."
        )
    return health.model_dump(mode="json", exclude_unset=True)


async def transcription_service_health(settings: ProviderSettings) -> dict[str, JsonValue]:
    routed = await route_request(settings, "transcription", _transcription_service_health_endpoint)
    payload = dict(routed.value)
    payload["endpoint"] = {
        "id": routed.endpoint.id,
        "name": routed.endpoint.name,
        "provider": routed.endpoint.provider,
        "model": routed.endpoint.model,
    }
    return payload


async def _transcribe_file_endpoint(settings: ProviderSettings, audio_path: Path) -> TranscriptResult:
    """Send one chapter clip to the configured timestamped ASR service."""
    provider = transcription_provider_name(settings)
    if provider == "none":
        raise RuntimeError("Configure a transcription provider in Audio Settings.")

    data = {}
    if settings.transcription_model:
        data["model"] = settings.transcription_model
    if settings.transcription_language and settings.transcription_language.lower() != "auto":
        data["language"] = settings.transcription_language

    timeout = httpx.Timeout(4 * 60 * 60.0, connect=20.0)
    with audio_path.open("rb") as audio:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{_service_root(settings)}/transcribe",
                data=data,
                files={"file": (audio_path.name, audio, "audio/flac")},
                headers=_headers(settings),
            )
            _raise_for_status(response, "request")
            payload = response.json()

    try:
        transcript = TranscriptionResponse.model_validate(payload)
    except ValidationError as exc:
        raise RuntimeError("Transcription service returned an invalid transcript or word timestamp.") from exc
    words = []
    for raw in transcript.words:
        text = raw.word.strip()
        start_ms = round(raw.start * 1000)
        end_ms = round(raw.end * 1000)
        if text and end_ms > start_ms:
            words.append(TranscriptWord(text=text, start_ms=start_ms, end_ms=end_ms, score=raw.score))
    if not words:
        raise RuntimeError("Transcription service returned no timestamped words.")
    last_end_ms = max(word.end_ms for word in words)
    duration_ms = round(transcript.duration * 1000) if transcript.duration is not None else last_end_ms
    return TranscriptResult(
        language=transcript.language,
        duration_ms=max(duration_ms, last_end_ms),
        words=words,
    )


async def transcribe_file(settings: ProviderSettings, audio_path: Path) -> TranscriptResult:
    """Transcribe through the first available endpoint."""
    routed = await route_request(
        settings,
        "transcription",
        lambda endpoint_settings: _transcribe_file_endpoint(endpoint_settings, audio_path),
    )
    return routed.value
