"""Provider-neutral text-to-speech clients used by the audiobook pipeline."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
import shutil

import httpx

from ..models import AudiobookSettings

DEFAULT_VOICE_PROMPT = "[gender-neutral][pitch-medium][speed-normal]"
SUPPORTED_TTS_PROVIDERS = {
    "stub",
    "omnivoice",
    "openai",
    "openai-compatible",
    "elevenlabs",
}

_PROFILE_TOKEN_RE = re.compile(r"\[([a-z]+)-([^\]]+)\]", re.IGNORECASE)
_EXPRESSION_TAG_RE = re.compile(
    r"\[(?:laughter|laugh|sigh|whisper|shout)\]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice_prompt: str = DEFAULT_VOICE_PROMPT
    voice_id: str | None = None


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


def _openai_speech_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/audio/speech"):
        return root
    if root.endswith("/v1"):
        return root + "/audio/speech"
    return root + "/v1/audio/speech"


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
    provider = (settings.tts_provider if settings else None) or "stub"
    provider = provider.strip().lower()
    if provider not in SUPPORTED_TTS_PROVIDERS:
        choices = ", ".join(sorted(SUPPORTED_TTS_PROVIDERS))
        raise RuntimeError(f"Unsupported TTS provider {provider!r}. Choose one of: {choices}.")
    return provider


async def synthesize_speech(
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
    if provider == "omnivoice":
        if not settings.tts_base_url:
            raise RuntimeError("OmniVoice base URL is required in Audio Settings.")
        url = settings.tts_base_url.rstrip("/")
        if not url.endswith("/generate"):
            url += "/generate"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json={"voice": request.voice_prompt, "text": request.text},
                headers={"Accept": "audio/mpeg"},
            )
            response.raise_for_status()
            return response.content

    voice_id = request.voice_id or settings.tts_default_voice
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
