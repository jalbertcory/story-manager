"""Clients for timestamped speech-to-text services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from ..models import AudiobookSettings

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


def transcription_provider_name(settings: AudiobookSettings | None) -> str:
    provider = (settings.transcription_provider if settings else None) or "none"
    provider = provider.strip().lower()
    if provider not in SUPPORTED_TRANSCRIPTION_PROVIDERS:
        choices = ", ".join(sorted(SUPPORTED_TRANSCRIPTION_PROVIDERS))
        raise RuntimeError(f"Unsupported transcription provider {provider!r}. Choose one of: {choices}.")
    return provider


def _service_root(settings: AudiobookSettings) -> str:
    if not settings.transcription_base_url:
        raise RuntimeError("Transcription service base URL is required in Audio Settings.")
    root = settings.transcription_base_url.rstrip("/")
    if root.endswith("/transcribe"):
        root = root[: -len("/transcribe")]
    return root


def _headers(settings: AudiobookSettings) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if settings.transcription_api_key:
        headers["Authorization"] = f"Bearer {settings.transcription_api_key}"
    return headers


async def transcription_service_health(settings: AudiobookSettings) -> dict:
    if transcription_provider_name(settings) == "none":
        raise RuntimeError("Configure a transcription provider first.")
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{_service_root(settings)}/health", headers=_headers(settings))
        response.raise_for_status()
        payload = response.json()
    if payload.get("status") != "ready":
        raise RuntimeError(f"Transcription service is not ready: {payload.get('status', 'unknown')}.")
    return payload


async def transcribe_file(settings: AudiobookSettings, audio_path: Path) -> TranscriptResult:
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
            response.raise_for_status()
            payload = response.json()

    raw_words = payload.get("words")
    if not isinstance(raw_words, list):
        raise RuntimeError("Transcription service response has no word timestamps.")
    words = []
    for raw in raw_words:
        try:
            text = str(raw["word"]).strip()
            start_ms = round(float(raw["start"]) * 1000)
            end_ms = round(float(raw["end"]) * 1000)
            score = float(raw.get("score", 1.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Transcription service returned an invalid word timestamp.") from exc
        if text and end_ms > start_ms >= 0:
            words.append(
                TranscriptWord(
                    text=text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    score=max(0.0, min(1.0, score)),
                )
            )
    if not words:
        raise RuntimeError("Transcription service returned no timestamped words.")
    duration_ms = round(float(payload.get("duration") or words[-1].end_ms / 1000) * 1000)
    return TranscriptResult(
        language=payload.get("language"),
        duration_ms=max(duration_ms, words[-1].end_ms),
        words=words,
    )
