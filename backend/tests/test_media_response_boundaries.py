"""Malformed media-provider JSON never becomes timestamps or extraction commands."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from backend.app.services import audiobook_import, audiobook_metadata, transcription_providers
from backend.app.services.endpoint_pool import EndpointSettings
from backend.app.services.media_responses import AudioProbe, TranscriptionResponse


@pytest.mark.parametrize(
    "patch",
    [
        {"words": [None]},
        {"words": [{"word": {}, "start": 0, "end": 1}]},
        {"words": [{"word": "hi", "start": True, "end": 1}]},
        {"words": [{"word": "hi", "start": -1, "end": 1}]},
        {"words": [{"word": "hi", "start": 2, "end": 1}]},
        {"words": [{"word": "hi", "start": 0, "end": float("inf")}]},
        {"words": [{"word": "hi", "start": 0, "end": 1, "score": float("nan")}]},
        {"words": [{"word": "hi", "start": 0, "end": 1, "score": 2}]},
        {"duration": -1},
        {"duration": float("inf")},
        {"language": ["en"]},
    ],
)
@pytest.mark.asyncio
async def test_transcription_boundary_rejects_invalid_fields(patch, tmp_path, monkeypatch):
    payload = {"words": [{"word": "hi", "start": 0, "end": 1}], **patch}
    # json() is mocked so non-finite values also exercise validation.
    response = SimpleNamespace(json=lambda: payload, raise_for_status=lambda: None)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.return_value = response
    monkeypatch.setattr(transcription_providers.httpx, "AsyncClient", lambda **kw: client)
    clip = tmp_path / "clip.flac"
    clip.write_bytes(b"audio")
    settings = EndpointSettings(transcription_provider="whisperx", transcription_base_url="http://asr")
    with pytest.raises(RuntimeError, match="invalid transcript"):
        await transcription_providers._transcribe_file_endpoint(settings, clip)


@pytest.mark.asyncio
async def test_transcription_optional_fields_and_duration_cover_all_words(tmp_path, monkeypatch):
    payload = {
        "words": [
            {"word": " earlier ", "start": 0, "end": 2},
            {"word": "overlap", "start": 1, "end": 1.5},
            {"word": "", "start": 2, "end": 2},
        ]
    }
    response = httpx.Response(200, json=payload, request=httpx.Request("POST", "http://asr/transcribe"))
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.return_value = response
    monkeypatch.setattr(transcription_providers.httpx, "AsyncClient", lambda **kw: client)
    clip = tmp_path / "clip.flac"
    clip.write_bytes(b"audio")
    result = await transcription_providers._transcribe_file_endpoint(
        EndpointSettings(transcription_provider="whisperx", transcription_base_url="http://asr"), clip
    )
    assert result.language is None
    assert result.duration_ms == 2000
    assert [word.text for word in result.words] == ["earlier", "overlap"]
    assert result.words[0].score == 1


@pytest.mark.parametrize("payload", [[], {"status": "ready", "model": 12}, {"status": True}])
@pytest.mark.asyncio
async def test_health_boundary_rejects_invalid_payload(payload, monkeypatch):
    response = httpx.Response(200, json=payload, request=httpx.Request("GET", "http://asr/health"))
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = response
    monkeypatch.setattr(transcription_providers.httpx, "AsyncClient", lambda **kw: client)
    with pytest.raises(RuntimeError, match="invalid health response"):
        await transcription_providers._transcription_service_health_endpoint(
            EndpointSettings(transcription_provider="whisperx", transcription_base_url="http://asr")
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"format": {"duration": "NaN"}},
        {"format": {"duration": True}},
        {"format": {"duration": "-1"}},
        {"format": {"tags": {"title": {"bad": "value"}}}},
        {"streams": [{"index": "0", "disposition": {"attached_pic": 1}}]},
        {"streams": [{"index": 0, "disposition": {"attached_pic": "yes"}}]},
    ],
)
def test_ffprobe_schema_rejects_invalid_nested_data(payload):
    with pytest.raises(ValidationError):
        AudioProbe.model_validate(payload)


@pytest.mark.asyncio
async def test_ffprobe_import_preserves_numeric_strings_chapters_and_tags(tmp_path, monkeypatch):
    payload = {
        "format": {"duration": "3.125", "tags": {"title": "Book"}},
        "chapters": [{"start_time": "0.0", "end_time": "3.125", "tags": {"title": "Opening"}}],
        "streams": [{"index": 1, "disposition": {"attached_pic": 1}}],
        "unknown_future_field": {},
    }
    process = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(json.dumps(payload).encode(), b"")))
    monkeypatch.setattr(audiobook_import.shutil, "which", lambda name: name)
    monkeypatch.setattr(audiobook_import.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    specs, duration = await audiobook_import._track_specs([tmp_path / "book.m4b"], [])
    assert duration == 3125
    assert specs[0].title == "Opening"
    assert (specs[0].start_ms, specs[0].end_ms) == (0, 3125)
    assert audiobook_metadata.tag_metadata(payload, single_file=True) == {"title": "Book"}
    assert AudioProbe.model_validate(payload).streams[0].index == 1


def test_transcription_schema_preserves_optional_defaults():
    payload = TranscriptionResponse.model_validate({"words": [{"word": "hello", "start": 0, "end": 1}]})
    assert payload.duration is None
    assert payload.words[0].score == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("keep_valid", [True, False])
async def test_invalid_optional_chapters_preserve_playable_audio(tmp_path, monkeypatch, keep_valid):
    chapters = [
        {"start_time": "2", "end_time": "1"},
        {"start_time": "1", "end_time": "1"},
        {"start_time": "-1", "end_time": "1"},
        {"start_time": "NaN", "end_time": "1"},
        None,
    ]
    if keep_valid:
        chapters.append({"start_time": "0", "end_time": "3", "tags": {"title": "Opening"}})
    payload = {"format": {"duration": "3"}, "chapters": chapters}
    process = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(json.dumps(payload).encode(), b"")))
    monkeypatch.setattr(audiobook_import.shutil, "which", lambda name: name)
    monkeypatch.setattr(audiobook_import.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    specs, duration = await audiobook_import._track_specs([tmp_path / "book.m4b"], [])
    assert duration == 3000
    assert len(specs) == 1
    assert specs[0].title == ("Opening" if keep_valid else "book")
    assert (specs[0].start_ms, specs[0].end_ms) == (0, 3000)


@pytest.mark.asyncio
async def test_invalid_transcription_response_fails_over(tmp_path, monkeypatch):
    from backend.app.endpoint_types import EndpointConfig
    from backend.app.services import endpoint_pool

    endpoint_pool.reset_cooldowns("transcription")
    urls = []

    async def post(url, **kwargs):
        urls.append(url)
        payload = {"words": [{"word": "hello", "start": 0, "end": 1}]}
        if "bad-asr" in url:
            payload["language"] = ["invalid"]
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.side_effect = post
    monkeypatch.setattr(transcription_providers.httpx, "AsyncClient", lambda **kw: client)
    clip = tmp_path / "clip.flac"
    clip.write_bytes(b"audio")
    settings = EndpointSettings(
        transcription_endpoints=[
            EndpointConfig(id="bad-asr", provider="whisperx", base_url="http://bad-asr"),
            EndpointConfig(id="good-asr", provider="whisperx", base_url="http://good-asr"),
        ]
    )
    try:
        result = await transcription_providers.transcribe_file(settings, clip)
        assert result.words[0].text == "hello"
        assert urls == ["http://bad-asr/transcribe", "http://good-asr/transcribe"]
    finally:
        endpoint_pool.reset_cooldowns("transcription")
