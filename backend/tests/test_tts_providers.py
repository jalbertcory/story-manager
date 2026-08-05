import base64

import pytest

from backend.app import models
from backend.app.services import endpoint_pool, tts_providers
from backend.app.services.tts_providers import TTSRequest


class _Response:
    def __init__(self, payload=None, *, content=b"mp3-bytes", headers=None):
        self.payload = payload
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        if self.payload is not None:
            return self.payload
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
        if url.endswith("/voices/design"):
            return _Response(
                {
                    "id": "omnivoice-0123456789abcdef0123456789abcdef",
                    "sample_text": "Reference text.",
                    "sample_url": "/voices/example/sample",
                }
            )
        if url.endswith("/generate-batch"):
            items = [
                {
                    "audio_base64": base64.b64encode(audio).decode(),
                    "duration_ms": duration,
                }
                for audio, duration in [(b"first-mp3", 1100), (b"second-mp3", 2200)][: len(kwargs["json"]["requests"])]
            ]
            return _Response({"items": items})
        return _Response()

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(content=b"reference-wav", headers={"content-type": "audio/wav"})


@pytest.fixture(autouse=True)
def fake_http_client(monkeypatch):
    _Client.calls = []
    endpoint_pool.reset_cooldowns()
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
        "voice_id": None,
        "text": "[whisper] Keep quiet.",
    }


@pytest.mark.asyncio
async def test_omnivoice_fetches_persisted_voice_design_sample():
    settings = models.AudiobookSettings(
        tts_provider="omnivoice",
        tts_base_url="http://omnivoice:8001/generate",
    )

    sample = await tts_providers.get_omnivoice_voice_sample(
        settings,
        "omnivoice-0123456789abcdef0123456789abcdef",
    )

    assert sample.audio_bytes == b"reference-wav"
    assert sample.media_type == "audio/wav"
    url, request = _Client.calls[0]
    assert url == ("http://omnivoice:8001/voices/" "omnivoice-0123456789abcdef0123456789abcdef/sample")
    assert request["headers"] == {"Accept": "audio/wav"}


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
            {"voice": "[gender-female]", "voice_id": None, "text": "First."},
            {"voice": "[gender-male]", "voice_id": None, "text": "Second."},
        ]
    }


@pytest.mark.asyncio
async def test_omnivoice_reuses_character_voice_id_for_single_and_batch_requests():
    settings = models.AudiobookSettings(
        tts_provider="omnivoice",
        tts_base_url="http://omnivoice:8001/generate",
    )
    request = TTSRequest(
        text="Consistent voice.",
        voice_prompt="[gender-male][pitch-low]",
        voice_id="omnivoice-0123456789abcdef0123456789abcdef",
        voice_provider="omnivoice",
    )

    await tts_providers.synthesize_speech(settings, request)
    await tts_providers.synthesize_speech_batch(settings, [request])

    assert _Client.calls[0][1]["json"]["voice_id"] == request.voice_id
    assert _Client.calls[1][1]["json"]["requests"][0]["voice_id"] == request.voice_id


@pytest.mark.asyncio
async def test_design_omnivoice_voice_returns_durable_provider_id():
    settings = models.AudiobookSettings(
        tts_provider="omnivoice",
        tts_base_url="http://omnivoice:8001/generate",
    )

    designed = await tts_providers.design_omnivoice_voice(
        settings,
        "female, low pitch, british accent",
    )

    assert designed.id == "omnivoice-0123456789abcdef0123456789abcdef"
    url, request = _Client.calls[0]
    assert url == "http://omnivoice:8001/voices/design"
    assert request["json"] == {"voice": "female, low pitch, british accent"}


@pytest.mark.asyncio
async def test_punctuation_only_batch_uses_local_silence(monkeypatch):
    settings = models.AudiobookSettings(
        tts_provider="omnivoice",
        tts_base_url="http://omnivoice:8001",
    )

    async def silence(_text):
        return b"silent-mp3"

    monkeypatch.setattr(tts_providers, "_stub_speech", silence)

    results = await tts_providers.synthesize_speech_batch(
        settings,
        [TTSRequest(text="."), TTSRequest(text="[sigh] !")],
    )

    assert [result.audio_bytes for result in results] == [b"silent-mp3", b"silent-mp3"]
    assert _Client.calls == []


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
async def test_fallback_provider_uses_its_own_default_voice():
    settings = models.AudiobookSettings(
        tts_provider="openai-compatible",
        tts_base_url="http://kokoro:8880",
        tts_model="kokoro",
        tts_default_voice="af_heart",
    )

    await tts_providers.synthesize_speech(
        settings,
        TTSRequest(
            text="Hello.",
            voice_id="elevenlabs-character-id",
            voice_provider="elevenlabs",
        ),
    )

    _url, request = _Client.calls[0]
    assert request["json"]["voice"] == "af_heart"


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
