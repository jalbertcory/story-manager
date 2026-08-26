"""Provider-neutral text-to-speech clients used by the audiobook pipeline."""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass
import re
import shutil

import httpx

from ..models import AudiobookSettings
from .endpoint_pool import RoutedResult, primary_provider, route_request

DEFAULT_VOICE_PROMPT = "[gender-neutral][pitch-medium][speed-normal]"
SUPPORTED_TTS_PROVIDERS = {
    "stub",
    "omnivoice",
    "qwen3",
    "openai",
    "openai-compatible",
    "elevenlabs",
}

_PROFILE_TOKEN_RE = re.compile(r"\[([a-z]+)-([^\]]+)\]", re.IGNORECASE)
_EXPRESSION_TAG_RE = re.compile(
    r"\[(?:laughter|laugh|sigh|whisper|shout|surprise-oh|dissatisfaction-hnn|confirmation-en)\]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice_prompt: str = DEFAULT_VOICE_PROMPT
    voice_id: str | None = None
    voice_provider: str | None = None
    seed: int | None = None
    min_voice_similarity: float | None = None
    quality_attempts: int = 3


@dataclass(frozen=True)
class TTSResult:
    audio_bytes: bytes
    duration_ms: int | None = None
    voice_similarity: float | None = None
    attempts: int | None = None


@dataclass(frozen=True)
class DesignedVoice:
    id: str
    sample_text: str
    sample_url: str
    max_cross_voice_similarity: float | None = None
    attempts: int = 1


@dataclass(frozen=True)
class VoiceSample:
    audio_bytes: bytes
    media_type: str


def _profile_tokens(prompt: str) -> dict[str, str]:
    return {key.lower(): value.lower() for key, value in _PROFILE_TOKEN_RE.findall(prompt)}


def _speech_speed(prompt: str) -> float:
    return {
        "slow": 0.85,
        "normal": 1.0,
        "fast": 1.15,
    }.get(_profile_tokens(prompt).get("speed", "normal"), 1.0)


def _voice_instructions(prompt: str) -> str | None:
    tokens = _profile_tokens(prompt)
    instructions: list[str] = []
    if gender := tokens.get("gender"):
        instructions.append(f"Use a {gender} voice")
    if age := tokens.get("age"):
        instructions.append(f"with a {age} age quality")
    if pitch := tokens.get("pitch"):
        instructions.append(f"with a {pitch} pitch")
    if accent := tokens.get("accent"):
        instructions.append(f"and a {accent} accent")

    remaining = _PROFILE_TOKEN_RE.sub("", prompt).strip()
    if remaining:
        instructions.append(remaining)
    return ". ".join(instructions) or None


def _plain_text(text: str) -> str:
    """Remove pipeline expression tags that non-OmniVoice APIs may speak aloud."""
    return " ".join(_EXPRESSION_TAG_RE.sub("", text).split())


def _has_spoken_content(text: str) -> bool:
    """Return whether text contains something a speech model can pronounce."""
    return any(character.isalnum() for character in _plain_text(text))


def _openai_speech_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/audio/speech"):
        return root
    if root.endswith("/v1"):
        return root + "/audio/speech"
    return root + "/v1/audio/speech"


def _local_tts_root(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/generate"):
        root = root[: -len("/generate")]
    return root


def _request_voice_id(request: TTSRequest, provider: str) -> str | None:
    if request.voice_provider and request.voice_provider != provider:
        return None
    return request.voice_id


def _local_request_payload(request: TTSRequest, provider: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "voice": request.voice_prompt,
        "voice_id": _request_voice_id(request, provider),
        "text": request.text,
    }
    if request.seed is not None:
        payload["seed"] = request.seed
    if request.min_voice_similarity is not None:
        payload["min_voice_similarity"] = request.min_voice_similarity
    if request.quality_attempts != 3:
        payload["quality_attempts"] = request.quality_attempts
    return payload


async def _stub_speech(text: str) -> bytes:
    duration_ms = max(350, min(5000, len(text.split()) * 260))
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required by the local audiobook TTS harness.")
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=22050:cl=mono",
        "-t",
        f"{duration_ms / 1000:.3f}",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "64k",
        "-f",
        "mp3",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        message = stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Local TTS harness failed: {message}")
    return stdout


def tts_provider_name(settings: AudiobookSettings | None) -> str:
    provider = primary_provider(settings, "tts", "stub")
    if provider not in SUPPORTED_TTS_PROVIDERS:
        choices = ", ".join(sorted(SUPPORTED_TTS_PROVIDERS))
        raise RuntimeError(f"Unsupported TTS provider {provider!r}. Choose one of: {choices}.")
    return provider


async def _synthesize_speech_endpoint(
    settings: AudiobookSettings | None,
    request: TTSRequest,
) -> bytes:
    """Generate an MP3 using the selected provider."""
    provider = tts_provider_name(settings)
    if provider == "stub":
        return await _stub_speech(request.text)
    if settings is None:
        raise RuntimeError("TTS settings are missing.")

    timeout = httpx.Timeout(600.0, connect=10.0)
    if provider in {"omnivoice", "qwen3"}:
        if not settings.tts_base_url:
            raise RuntimeError(f"{provider} base URL is required in Audio Settings.")
        url = f"{_local_tts_root(settings.tts_base_url)}/generate"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json=_local_request_payload(request, provider),
                headers={"Accept": "audio/mpeg"},
            )
            response.raise_for_status()
            return response.content

    endpoint_voice_id = _request_voice_id(request, provider)
    voice_id = endpoint_voice_id or settings.tts_default_voice
    if not voice_id:
        raise RuntimeError(
            f"A voice ID is required for the {provider} TTS provider. "
            "Set a default voice in Audio Settings or one on the character."
        )

    if provider in {"openai", "openai-compatible"}:
        base_url = settings.tts_base_url or ("https://api.openai.com" if provider == "openai" else None)
        if not base_url:
            raise RuntimeError("A base URL is required for an OpenAI-compatible TTS provider.")
        if provider == "openai" and not settings.tts_api_key:
            raise RuntimeError("An API key is required for OpenAI TTS.")

        model = settings.tts_model or ("tts-1" if provider == "openai" else None)
        if not model:
            raise RuntimeError("A model name is required for an OpenAI-compatible TTS provider.")
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        }
        if settings.tts_api_key:
            headers["Authorization"] = f"Bearer {settings.tts_api_key}"
        payload: dict[str, object] = {
            "model": model,
            "voice": voice_id,
            "input": _plain_text(request.text),
            "response_format": "mp3",
            "speed": _speech_speed(request.voice_prompt),
        }
        # OpenAI's tts-1 family rejects instructions. Compatible servers often
        # reject unknown fields, so only send this to instruction-capable
        # OpenAI models selected explicitly by the user.
        if provider == "openai" and not model.startswith("tts-1"):
            instructions = _voice_instructions(request.voice_prompt)
            if instructions:
                payload["instructions"] = instructions

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                _openai_speech_url(base_url),
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.content

    if not settings.tts_api_key:
        raise RuntimeError("An API key is required for ElevenLabs TTS.")
    base_url = (settings.tts_base_url or "https://api.elevenlabs.io").rstrip("/")
    model = settings.tts_model or "eleven_multilingual_v2"
    api_root = base_url if base_url.endswith("/v1") else f"{base_url}/v1"
    url = f"{api_root}/text-to-speech/{voice_id}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            url,
            params={"output_format": "mp3_44100_128"},
            json={
                "text": _plain_text(request.text),
                "model_id": model,
                "voice_settings": {"speed": _speech_speed(request.voice_prompt)},
            },
            headers={
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": settings.tts_api_key,
            },
        )
        response.raise_for_status()
        return response.content


async def synthesize_speech_result_routed(
    settings: AudiobookSettings,
    request: TTSRequest,
) -> RoutedResult[TTSResult]:
    return await route_request(
        settings,
        "tts",
        lambda endpoint_settings: _synthesize_speech_result_endpoint(endpoint_settings, request),
    )


async def synthesize_speech_routed(
    settings: AudiobookSettings,
    request: TTSRequest,
) -> RoutedResult[bytes]:
    """Compatibility route for health tests that only need the audio bytes."""
    return await route_request(
        settings,
        "tts",
        lambda endpoint_settings: _synthesize_speech_endpoint(endpoint_settings, request),
    )


async def _synthesize_speech_result_endpoint(
    settings: AudiobookSettings | None,
    request: TTSRequest,
) -> TTSResult:
    provider = tts_provider_name(settings)
    if provider not in {"omnivoice", "qwen3"} or settings is None:
        return TTSResult(audio_bytes=await _synthesize_speech_endpoint(settings, request))
    if not settings.tts_base_url:
        raise RuntimeError(f"{provider} base URL is required in Audio Settings.")
    timeout = httpx.Timeout(600.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{_local_tts_root(settings.tts_base_url)}/generate",
            json=_local_request_payload(request, provider),
            headers={"Accept": "audio/mpeg"},
        )
        response.raise_for_status()
    return TTSResult(
        audio_bytes=response.content,
        duration_ms=_optional_int_header(response, "x-audio-duration-ms"),
        voice_similarity=_optional_float_header(response, "x-voice-similarity"),
        attempts=_optional_int_header(response, "x-generation-attempts"),
    )


def _optional_int_header(response: httpx.Response, name: str) -> int | None:
    value = response.headers.get(name)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _optional_float_header(response: httpx.Response, name: str) -> float | None:
    value = response.headers.get(name)
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


async def synthesize_speech(
    settings: AudiobookSettings | None,
    request: TTSRequest,
) -> bytes:
    """Generate an MP3 using the first available endpoint."""
    if not _has_spoken_content(request.text):
        return await _stub_speech("")
    if settings is None:
        return await _stub_speech(request.text)
    routed = await route_request(
        settings,
        "tts",
        lambda endpoint_settings: _synthesize_speech_endpoint(endpoint_settings, request),
    )
    return routed.value


async def synthesize_speech_result(
    settings: AudiobookSettings | None,
    request: TTSRequest,
) -> TTSResult:
    if not _has_spoken_content(request.text):
        return TTSResult(await _stub_speech(""))
    if settings is None:
        return TTSResult(await _stub_speech(request.text))
    routed = await synthesize_speech_result_routed(settings, request)
    return routed.value


async def _design_local_voice_endpoint(
    settings: AudiobookSettings,
    voice_prompt: str,
    *,
    seed: int | None = None,
    avoid_voice_ids: list[str] | None = None,
    max_voice_similarity: float = 0.9,
    quality_attempts: int = 6,
) -> DesignedVoice:
    provider = tts_provider_name(settings)
    if provider not in {"omnivoice", "qwen3"}:
        raise RuntimeError("Consistent voice design is only available for a local design-capable provider.")
    if not settings.tts_base_url:
        raise RuntimeError(f"{provider} base URL is required in Audio Settings.")
    timeout = httpx.Timeout(600.0, connect=10.0)
    payload: dict[str, object] = {"voice": voice_prompt}
    if provider == "qwen3":
        if seed is not None:
            payload["seed"] = seed
        if avoid_voice_ids:
            payload["avoid_voice_ids"] = list(dict.fromkeys(avoid_voice_ids))
            payload["max_voice_similarity"] = max_voice_similarity
        payload["quality_attempts"] = quality_attempts
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{_local_tts_root(settings.tts_base_url)}/voices/design",
            json=payload,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    try:
        return DesignedVoice(
            id=str(payload["id"]),
            sample_text=str(payload["sample_text"]),
            sample_url=str(payload["sample_url"]),
            max_cross_voice_similarity=(
                float(payload["max_cross_voice_similarity"]) if payload.get("max_cross_voice_similarity") is not None else None
            ),
            attempts=int(payload.get("attempts", 1)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{provider} returned an invalid designed voice.") from exc


async def design_omnivoice_voice(
    settings: AudiobookSettings,
    voice_prompt: str,
    *,
    seed: int | None = None,
    avoid_voice_ids: list[str] | None = None,
    max_voice_similarity: float = 0.9,
    quality_attempts: int = 6,
) -> DesignedVoice:
    """Create a stateful reference on the primary local worker."""
    return await _design_local_voice_endpoint(
        settings,
        voice_prompt,
        seed=seed,
        avoid_voice_ids=avoid_voice_ids,
        max_voice_similarity=max_voice_similarity,
        quality_attempts=quality_attempts,
    )


design_local_voice = design_omnivoice_voice


async def materialize_qwen_preset_voice(
    settings: AudiobookSettings,
    preset_voice_id: str,
    voice_prompt: str,
    *,
    seed: int | None = None,
    avoid_voice_ids: list[str] | None = None,
    max_voice_similarity: float = 0.9,
) -> DesignedVoice:
    """Persist an official Qwen speaker as a clone so synthesis stays on one model."""
    if tts_provider_name(settings) != "qwen3" or not settings.tts_base_url:
        raise RuntimeError("Qwen3 base URL is required to materialize a preset voice.")
    payload: dict[str, object] = {
        "voice_id": preset_voice_id,
        "voice": voice_prompt,
    }
    if seed is not None:
        payload["seed"] = seed
    if avoid_voice_ids:
        payload["avoid_voice_ids"] = list(dict.fromkeys(avoid_voice_ids))
        payload["max_voice_similarity"] = max_voice_similarity
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
        response = await client.post(
            f"{_local_tts_root(settings.tts_base_url)}/voices/from-preset",
            json=payload,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        response_payload = response.json()
    try:
        return DesignedVoice(
            id=str(response_payload["id"]),
            sample_text=str(response_payload["sample_text"]),
            sample_url=str(response_payload["sample_url"]),
            max_cross_voice_similarity=(
                float(response_payload["max_cross_voice_similarity"])
                if response_payload.get("max_cross_voice_similarity") is not None
                else None
            ),
            attempts=int(response_payload.get("attempts", 1)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Qwen3 returned an invalid materialized preset voice.") from exc


async def _get_local_voice_sample_endpoint(
    settings: AudiobookSettings,
    voice_id: str,
) -> VoiceSample:
    provider = tts_provider_name(settings)
    if provider not in {"omnivoice", "qwen3"}:
        raise RuntimeError("Voice samples are only available for a local design-capable provider.")
    if not settings.tts_base_url:
        raise RuntimeError(f"{provider} base URL is required in Audio Settings.")
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{_local_tts_root(settings.tts_base_url)}/voices/{voice_id}/sample",
            headers={"Accept": "audio/wav"},
        )
        response.raise_for_status()
    media_type = response.headers.get("content-type", "audio/wav").split(";", 1)[0]
    return VoiceSample(audio_bytes=response.content, media_type=media_type)


async def get_omnivoice_voice_sample(
    settings: AudiobookSettings,
    voice_id: str,
) -> VoiceSample:
    """Fetch a durable reference from the primary worker that created it."""
    return await _get_local_voice_sample_endpoint(settings, voice_id)


get_local_voice_sample = get_omnivoice_voice_sample


async def synthesize_speech_batch(
    settings: AudiobookSettings | None,
    requests: list[TTSRequest],
) -> list[TTSResult]:
    """Generate a true model batch when supported, with a sequential fallback."""
    if not requests:
        return []

    spoken_requests = [request for request in requests if _has_spoken_content(request.text)]
    if settings is None:
        spoken_results = [TTSResult(await _stub_speech(request.text)) for request in spoken_requests]
    elif spoken_requests:
        routed = await route_request(
            settings,
            "tts",
            lambda endpoint_settings: _synthesize_speech_batch_endpoint(endpoint_settings, spoken_requests),
        )
        spoken_results = routed.value
    else:
        spoken_results = []

    if len(spoken_requests) == len(requests):
        return spoken_results

    silence = TTSResult(await _stub_speech(""))
    spoken = iter(spoken_results)
    return [next(spoken) if _has_spoken_content(request.text) else silence for request in requests]


async def _synthesize_speech_batch_endpoint(
    settings: AudiobookSettings,
    requests: list[TTSRequest],
) -> list[TTSResult]:
    """Generate one batch against a specific endpoint."""
    provider = tts_provider_name(settings)
    if provider not in {"omnivoice", "qwen3"}:
        return [TTSResult(await _synthesize_speech_endpoint(settings, request)) for request in requests]
    if not settings.tts_base_url:
        raise RuntimeError(f"{provider} base URL is required in Audio Settings.")

    root = _local_tts_root(settings.tts_base_url)
    url = f"{root}/generate-batch"
    timeout = httpx.Timeout(600.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            url,
            json={"requests": [_local_request_payload(request, provider) for request in requests]},
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()

    items = payload.get("items")
    if not isinstance(items, list) or len(items) != len(requests):
        raise RuntimeError(
            f"{provider} returned {len(items) if isinstance(items, list) else 0} "
            f"batch results for {len(requests)} requests."
        )

    results: list[TTSResult] = []
    for item in items:
        try:
            audio_bytes = base64.b64decode(item["audio_base64"], validate=True)
            duration_ms = int(item["duration_ms"])
            similarity = float(item["voice_similarity"]) if item.get("voice_similarity") is not None else None
            attempts = int(item["attempts"]) if item.get("attempts") is not None else None
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise RuntimeError(f"{provider} returned an invalid batch result.") from exc
        if not audio_bytes or duration_ms <= 0:
            raise RuntimeError("OmniVoice returned an empty batch result.")
        results.append(
            TTSResult(
                audio_bytes=audio_bytes,
                duration_ms=duration_ms,
                voice_similarity=similarity,
                attempts=attempts,
            )
        )
    return results
