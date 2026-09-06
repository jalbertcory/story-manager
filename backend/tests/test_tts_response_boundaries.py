"""Malformed worker output must not become accepted audiobook state."""

import base64
import json

import httpx
import pytest

from backend.app.services import endpoint_pool, tts_providers
from backend.app.services.endpoint_pool import EndpointSettings
from backend.app.services.tts_providers import TTSRequest

VOICE = {"id": "voice-123", "sample_text": "Hello.", "sample_url": "/voices/voice-123/sample"}
ITEM = {"audio_base64": base64.b64encode(b"audio").decode(), "duration_ms": 1000}


@pytest.fixture
def mock_worker(monkeypatch):
    client_type = httpx.AsyncClient
    endpoint_pool.reset_cooldowns()

    def install(payload, *, raw=False):
        def handler(request):
            content = payload if raw else json.dumps(payload)
            return httpx.Response(200, content=content, request=request)

        monkeypatch.setattr(
            tts_providers.httpx,
            "AsyncClient",
            lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
        )

    yield install
    endpoint_pool.reset_cooldowns()


@pytest.fixture
def settings():
    return EndpointSettings(tts_provider="qwen3", tts_base_url="http://worker")


@pytest.mark.asyncio
@pytest.mark.parametrize("preset", [False, True])
@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {**VOICE, "id": None},
        {**VOICE, "id": "  "},
        {**VOICE, "sample_text": {}},
        {**VOICE, "sample_url": []},
        {**VOICE, "attempts": True},
        {**VOICE, "attempts": -2},
        {**VOICE, "attempts": 1.5},
        {**VOICE, "max_cross_voice_similarity": float("nan")},
        {**VOICE, "max_cross_voice_similarity": 1.1},
    ],
)
async def test_invalid_voice_responses_are_rejected(mock_worker, settings, preset, payload):
    mock_worker(payload)
    with pytest.raises(RuntimeError, match="returned an invalid"):
        if preset:
            await tts_providers.materialize_qwen_preset_voice(settings, "preset:Ryan", "voice")
        else:
            await tts_providers.design_local_voice(settings, "voice")


@pytest.mark.asyncio
@pytest.mark.parametrize("preset", [False, True])
async def test_voice_response_optional_fields_and_extensions(mock_worker, settings, preset):
    mock_worker({**VOICE, "voice": "description", "max_cross_voice_similarity": None, "future_field": {}})
    if preset:
        result = await tts_providers.materialize_qwen_preset_voice(settings, "preset:Ryan", "voice")
    else:
        result = await tts_providers.design_local_voice(settings, "voice")
    assert result == tts_providers.DesignedVoice(**VOICE)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"items": None},
        {"items": []},
        {"items": [None]},
        {"items": [ITEM, ITEM]},
        *[
            {"items": [{**ITEM, field: value}]}
            for field, value in [
                ("audio_base64", None),
                ("audio_base64", "invalid!"),
                ("audio_base64", ""),
                ("duration_ms", True),
                ("duration_ms", 0),
                ("duration_ms", -1),
                ("duration_ms", "1000"),
                ("duration_ms", 1.5),
                ("voice_similarity", float("nan")),
                ("voice_similarity", float("inf")),
                ("voice_similarity", "NaN"),
                ("voice_similarity", -1.1),
                ("attempts", False),
                ("attempts", -2),
            ]
        ],
    ],
)
async def test_invalid_batch_responses_are_rejected(mock_worker, settings, payload):
    mock_worker(payload)
    with pytest.raises(RuntimeError, match="returned"):
        await tts_providers.synthesize_speech_batch(settings, [TTSRequest("Hello.")])


@pytest.mark.asyncio
async def test_batch_preserves_order_nullable_metrics_and_cosine_range(mock_worker, settings):
    mock_worker(
        {
            "items": [
                {**ITEM, "voice_similarity": -1.0, "attempts": 2},
                {**ITEM, "duration_ms": 2000, "voice_similarity": None, "attempts": None, "extra": True},
                ITEM,
            ]
        }
    )
    result = await tts_providers.synthesize_speech_batch(settings, [TTSRequest("Hello.")] * 3)
    assert result == [
        tts_providers.TTSResult(b"audio", 1000, -1.0, 2),
        tts_providers.TTSResult(b"audio", 2000),
        tts_providers.TTSResult(b"audio", 1000),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["design", "preset", "batch"])
async def test_non_json_response_has_a_useful_error(mock_worker, settings, operation):
    mock_worker("<html>unavailable</html>", raw=True)
    with pytest.raises(RuntimeError, match="returned an invalid"):
        if operation == "design":
            await tts_providers.design_local_voice(settings, "voice")
        elif operation == "preset":
            await tts_providers.materialize_qwen_preset_voice(settings, "preset:Ryan", "voice")
        else:
            await tts_providers.synthesize_speech_batch(settings, [TTSRequest("Hello.")])


@pytest.mark.asyncio
async def test_malformed_batch_fails_over_and_cools_down_endpoint(mock_worker, monkeypatch):
    client_type = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request.url.host)
        item = {**ITEM, "duration_ms": True} if request.url.host == "bad" else ITEM
        return httpx.Response(200, json={"items": [item]})

    monkeypatch.setattr(
        tts_providers.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    settings = EndpointSettings.model_validate(
        {
            "tts_endpoints": [
                {"id": host, "name": host, "provider": "qwen3", "base_url": f"http://{host}"} for host in ["bad", "good"]
            ]
        }
    )
    for _ in range(2):
        assert await tts_providers.synthesize_speech_batch(settings, [TTSRequest("Hello.")]) == [
            tts_providers.TTSResult(b"audio", 1000)
        ]
    assert calls == ["bad", "good", "good"]


@pytest.mark.parametrize("value", ["NaN", "inf", "-inf", "1.1", "-1.1", "invalid"])
def test_invalid_optional_similarity_headers_are_ignored(value):
    response = httpx.Response(200, headers={"x-voice-similarity": value})
    assert tts_providers._optional_float_header(response, "x-voice-similarity") is None


@pytest.mark.parametrize("value", ["0", "-2", "true", "1.5"])
def test_invalid_optional_count_headers_are_ignored(value):
    response = httpx.Response(200, headers={"x-generation-attempts": value})
    assert tts_providers._optional_int_header(response, "x-generation-attempts") is None
