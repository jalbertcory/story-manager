import base64

import pytest

from backend.app import models
from backend.app.services import tts_providers
from backend.app.services.tts_providers import TTSRequest


class _Response:
    content = b"mp3-bytes"

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "items": [
                {
                    "audio_base64": base64.b64encode(b"first-mp3").decode(),
                    "duration_ms": 1100,
                },
                {
                    "audio_base64": base64.b64encode(b"second-mp3").decode(),
                    "duration_ms": 2200,
                },
            ]
        }


class _Client:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response()


@pytest.fixture(autouse=True)
def fake_http_client(monkeypatch):
    _Client.calls = []
    monkeypatch.setattr(tts_providers.httpx, "AsyncClient", _Client)


@pytest.mark.asyncio
async def test_omnivoice_uses_descriptive_profile_and_expression_tags():
    settings = models.AudiobookSettings(
        tts_provider="omnivoice",
        tts_base_url="http://omnivoice:8001",
    )

    audio = await tts_providers.synthesize_speech(
        settings,
        TTSRequest(
            text="[whisper] Keep quiet.",
            voice_prompt="[gender-female][pitch-low][speed-slow]",
        ),
    )

    assert audio == b"mp3-bytes"
    url, request = _Client.calls[0]
    assert url == "http://omnivoice:8001/generate"
    assert request["json"] == {
        "voice": "[gender-female][pitch-low][speed-slow]",
        "text": "[whisper] Keep quiet.",
    }


@pytest.mark.asyncio
async def test_omnivoice_batches_multiple_sentences_in_one_model_request():
    settings = models.AudiobookSettings(
        tts_provider="omnivoice",
        tts_base_url="http://omnivoice:8001/generate",
    )

    results = await tts_providers.synthesize_speech_batch(
        settings,
        [
            TTSRequest(text="First.", voice_prompt="[gender-female]"),
            TTSRequest(text="Second.", voice_prompt="[gender-male]"),
        ],
    )

    assert [(result.audio_bytes, result.duration_ms) for result in results] == [
        (b"first-mp3", 1100),
        (b"second-mp3", 2200),
    ]
    url, request = _Client.calls[0]
    assert url == "http://omnivoice:8001/generate-batch"
    assert request["json"] == {
        "requests": [
            {"voice": "[gender-female]", "text": "First."},
            {"voice": "[gender-male]", "text": "Second."},
        ]
    }


@pytest.mark.asyncio
async def test_openai_compatible_uses_voice_id_and_compatible_payload():
    settings = models.AudiobookSettings(
        tts_provider="openai-compatible",
        tts_api_key="local-secret",
        tts_base_url="http://kokoro:8880/v1",
        tts_model="kokoro",
        tts_default_voice="af_heart",
    )

    await tts_providers.synthesize_speech(
        settings,
        TTSRequest(
            text="[sigh] This is a test.",
            voice_prompt="[gender-female][pitch-medium][speed-fast]",
            voice_id="bf_emma",
        ),
    )

    url, request = _Client.calls[0]
    assert url == "http://kokoro:8880/v1/audio/speech"
    assert request["headers"]["Authorization"] == "Bearer local-secret"
    assert request["json"] == {
        "model": "kokoro",
        "voice": "bf_emma",
        "input": "This is a test.",
        "response_format": "mp3",
        "speed": 1.15,
    }


@pytest.mark.asyncio
async def test_openai_instruction_capable_model_receives_voice_profile():
    settings = models.AudiobookSettings(
        tts_provider="openai",
        tts_api_key="secret",
        tts_model="instruction-capable-tts",
        tts_default_voice="alloy",
    )

    await tts_providers.synthesize_speech(
        settings,
        TTSRequest(
            text="Read this.",
            voice_prompt="[gender-neutral][pitch-low][accent-british] Calm and warm.",
        ),
    )

    url, request = _Client.calls[0]
    assert url == "https://api.openai.com/v1/audio/speech"
    assert "low pitch" in request["json"]["instructions"]
    assert "british accent" in request["json"]["instructions"]
    assert "Calm and warm." in request["json"]["instructions"]


@pytest.mark.asyncio
async def test_elevenlabs_uses_character_voice_override():
    settings = models.AudiobookSettings(
        tts_provider="elevenlabs",
        tts_api_key="secret",
        tts_model="eleven_multilingual_v2",
        tts_default_voice="default-id",
    )

    await tts_providers.synthesize_speech(
        settings,
        TTSRequest(
            text="Hello.",
            voice_prompt="[gender-neutral][pitch-medium][speed-fast]",
            voice_id="character-id",
        ),
    )

    url, request = _Client.calls[0]
    assert url == "https://api.elevenlabs.io/v1/text-to-speech/character-id"
    assert request["headers"]["xi-api-key"] == "secret"
    assert request["params"] == {"output_format": "mp3_44100_128"}
    assert request["json"] == {
        "text": "Hello.",
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"speed": 1.15},
    }


@pytest.mark.asyncio
async def test_fixed_voice_provider_requires_a_voice_id():
    settings = models.AudiobookSettings(
        tts_provider="openai-compatible",
        tts_base_url="http://tts:8880",
        tts_model="kokoro",
    )

    with pytest.raises(RuntimeError, match="voice ID is required"):
        await tts_providers.synthesize_speech(settings, TTSRequest(text="Hello."))
