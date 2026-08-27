import httpx
import pytest
from sqlalchemy import select

from backend.app import models
from backend.app.services import endpoint_metrics, endpoint_pool


@pytest.fixture(autouse=True)
def clear_endpoint_cooldowns():
    endpoint_pool.reset_cooldowns()
    yield
    endpoint_pool.reset_cooldowns()


@pytest.mark.asyncio
async def test_priority_endpoint_falls_back_and_is_skipped_during_cooldown(monkeypatch):
    now = 1000.0
    monkeypatch.setattr(endpoint_pool.time, "monotonic", lambda: now)
    settings = models.AudiobookSettings(
        llm_endpoints=[
            {
                "id": "gaming-pc",
                "name": "Gaming PC",
                "provider": "ollama",
                "base_url": "http://gaming:11434",
                "model": "qwen3.5:27b",
            },
            {
                "id": "mini-pc",
                "name": "Always-on mini PC",
                "provider": "ollama",
                "base_url": "http://mini:11434",
                "model": "qwen3.5:9b",
            },
        ]
    )
    gaming_online = False
    calls = []

    async def attempt(endpoint_settings):
        calls.append(endpoint_settings.llm_base_url)
        if endpoint_settings.llm_base_url == "http://gaming:11434" and not gaming_online:
            request = httpx.Request("POST", "http://gaming:11434/api/chat")
            raise httpx.ConnectError("offline", request=request)
        return endpoint_settings.llm_model

    first = await endpoint_pool.route_request(settings, "llm", attempt)
    assert first.value == "qwen3.5:9b"
    assert first.endpoint["id"] == "mini-pc"
    assert calls == ["http://gaming:11434", "http://mini:11434"]

    gaming_online = True
    calls.clear()
    second = await endpoint_pool.route_request(settings, "llm", attempt)
    assert second.endpoint["id"] == "mini-pc"
    assert calls == ["http://mini:11434"]

    now += 61
    calls.clear()
    third = await endpoint_pool.route_request(settings, "llm", attempt)
    assert third.value == "qwen3.5:27b"
    assert third.endpoint["id"] == "gaming-pc"
    assert calls == ["http://gaming:11434"]


@pytest.mark.asyncio
async def test_all_cooling_endpoints_fail_fast(monkeypatch):
    now = 2000.0
    monkeypatch.setattr(endpoint_pool.time, "monotonic", lambda: now)
    settings = models.AudiobookSettings(
        tts_endpoints=[
            {"id": "one", "name": "One", "provider": "omnivoice", "base_url": "http://one"},
            {"id": "two", "name": "Two", "provider": "omnivoice", "base_url": "http://two"},
        ]
    )

    async def fail(_endpoint_settings):
        raise RuntimeError("offline")

    with pytest.raises(RuntimeError, match="offline"):
        await endpoint_pool.route_request(settings, "tts", fail)
    with pytest.raises(RuntimeError, match="All tts endpoints are cooling down"):
        await endpoint_pool.route_request(settings, "tts", fail)


@pytest.mark.asyncio
async def test_pool_probe_tests_every_endpoint_and_ignores_cooldown(monkeypatch):
    now = 2000.0
    monkeypatch.setattr(endpoint_pool.time, "monotonic", lambda: now)
    settings = models.AudiobookSettings(
        tts_endpoints=[
            {"id": "qwen", "name": "Qwen", "provider": "qwen3", "base_url": "http://qwen"},
            {"id": "omni", "name": "OmniVoice", "provider": "omnivoice", "base_url": "http://omni"},
        ]
    )
    endpoint_pool._cooldowns[("tts", "qwen")] = now + 30
    calls = []

    async def attempt(endpoint_settings):
        calls.append(endpoint_settings.tts_base_url)
        if endpoint_settings.tts_provider == "qwen3":
            request = httpx.Request("POST", "http://qwen/generate")
            response = httpx.Response(
                409,
                json={"detail": "configured model is not loaded"},
                request=request,
            )
            raise httpx.HTTPStatusError(
                "Qwen request failed",
                request=request,
                response=response,
            )
        return b"audio"

    results = await endpoint_pool.probe_endpoints(settings, "tts", attempt)

    assert calls == ["http://qwen", "http://omni"]
    assert [(result.endpoint["id"], result.success) for result in results] == [
        ("qwen", False),
        ("omni", True),
    ]
    assert results[0].error == "Qwen request failed — configured model is not loaded"


def test_reset_cooldowns_can_target_one_capability(monkeypatch):
    monkeypatch.setattr(endpoint_pool.time, "monotonic", lambda: 1000.0)
    endpoint_pool._cooldowns.update(
        {
            ("tts", "voice-host"): 1060.0,
            ("llm", "language-host"): 1060.0,
        }
    )

    endpoint_pool.reset_cooldowns("tts")

    assert endpoint_pool._cooldowns == {("llm", "language-host"): 1060.0}


@pytest.mark.asyncio
async def test_provider_restricted_settings_never_fall_through_to_another_tts_engine():
    settings = models.AudiobookSettings(
        tts_endpoints=[
            {"id": "qwen-gaming", "provider": "qwen3", "base_url": "http://qwen-gaming"},
            {"id": "qwen-backup", "provider": "qwen3", "base_url": "http://qwen-backup"},
            {"id": "omni", "provider": "omnivoice", "base_url": "http://omni"},
        ]
    )
    restricted = endpoint_pool.settings_for_provider(settings, "tts", "qwen3")
    calls = []

    async def attempt(endpoint_settings):
        calls.append(endpoint_settings.tts_base_url)
        if endpoint_settings.tts_base_url == "http://qwen-gaming":
            raise RuntimeError("gaming PC offline")
        return endpoint_settings.tts_provider

    routed = await endpoint_pool.route_request(restricted, "tts", attempt)

    assert routed.value == "qwen3"
    assert routed.endpoint["id"] == "qwen-backup"
    assert calls == ["http://qwen-gaming", "http://qwen-backup"]


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["llm", "tts", "transcription"])
async def test_routes_record_successful_endpoint_attempt(monkeypatch, sqlite_sessionmaker, capability):
    monkeypatch.setattr(endpoint_metrics, "SessionLocal", sqlite_sessionmaker)
    endpoint = {
        "id": f"local-{capability}",
        "name": f"Local {capability}",
        "provider": "local",
        "base_url": "http://local",
        "model": "test-model",
    }
    async with sqlite_sessionmaker() as db:
        settings = models.AudiobookSettings(**{f"{capability}_endpoints": [endpoint]})
        db.add(settings)
        await db.commit()

    async def succeed(_endpoint_settings):
        return "answer"

    routed = await endpoint_pool.route_request(settings, capability, succeed)
    assert routed.value == "answer"

    async with sqlite_sessionmaker() as db:
        metric = await db.scalar(select(models.AiEndpointRequestMetric))
    assert metric is not None
    assert metric.capability == capability
    assert metric.endpoint_id == f"local-{capability}"
    assert metric.success is True
    assert metric.duration_ms >= 0


@pytest.mark.asyncio
async def test_endpoint_summaries_include_latency_percentiles_and_buckets(db):
    settings = models.AudiobookSettings(
        llm_endpoints=[
            {"id": "fast", "name": "Fast host", "provider": "ollama", "model": "small"},
            {"id": "unused", "name": "Unused host", "provider": "ollama", "model": "large"},
        ]
    )
    db.add(settings)
    await db.flush()
    for duration in (1_000, 10_000, 20_000, 70_000):
        db.add(
            models.AiEndpointRequestMetric(
                settings_id=settings.id,
                capability="llm",
                endpoint_id="fast",
                endpoint_name="Fast host",
                provider="ollama",
                model="small",
                success=True,
                duration_ms=duration,
            )
        )
    db.add(
        models.AiEndpointRequestMetric(
            settings_id=settings.id,
            capability="llm",
            endpoint_id="fast",
            endpoint_name="Fast host",
            provider="ollama",
            model="small",
            success=False,
            duration_ms=500,
            error_type="ConnectError",
        )
    )
    await db.commit()

    summaries = await endpoint_metrics.endpoint_summaries(db, settings, "llm")

    assert summaries[0]["requests"] == 5
    assert summaries[0]["answered"] == 4
    assert summaries[0]["failed"] == 1
    assert summaries[0]["success_rate"] == 80.0
    assert summaries[0]["average_ms"] == 25_250.0
    assert summaries[0]["p50_ms"] == 15_000.0
    assert summaries[0]["p95_ms"] == 62_500.0
    assert summaries[0]["speed_buckets"] == {
        "under_5s": 1,
        "from_5s_to_15s": 1,
        "from_15s_to_60s": 1,
        "over_60s": 1,
    }
    assert summaries[1]["requests"] == 0
    assert summaries[1]["average_ms"] is None


@pytest.mark.asyncio
async def test_llm_stats_api_returns_configured_endpoint_metrics(app_client, sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        settings = models.AudiobookSettings(llm_endpoints=[{"id": "api-host", "name": "API Host", "provider": "ollama"}])
        db.add(settings)
        await db.flush()
        db.add(
            models.AiEndpointRequestMetric(
                settings_id=settings.id,
                capability="llm",
                endpoint_id="api-host",
                endpoint_name="API Host",
                provider="ollama",
                success=True,
                duration_ms=1_250,
            )
        )
        await db.commit()

    response = app_client.get("/api/audiobook/settings/llm-stats")

    assert response.status_code == 200
    endpoint = response.json()["endpoints"][0]
    assert endpoint["name"] == "API Host"
    assert endpoint["answered"] == 1
    assert endpoint["average_ms"] == 1_250.0


@pytest.mark.asyncio
async def test_all_endpoint_stats_api_includes_tts_and_transcription(app_client, sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        settings = models.AudiobookSettings(
            llm_endpoints=[{"id": "llm-host", "name": "LLM Host", "provider": "ollama"}],
            tts_endpoints=[{"id": "tts-host", "name": "TTS Host", "provider": "omnivoice"}],
            transcription_endpoints=[{"id": "stt-host", "name": "STT Host", "provider": "whisperx"}],
        )
        db.add(settings)
        await db.flush()
        for capability, endpoint_id in (("tts", "tts-host"), ("transcription", "stt-host")):
            db.add(
                models.AiEndpointRequestMetric(
                    settings_id=settings.id,
                    capability=capability,
                    endpoint_id=endpoint_id,
                    endpoint_name=endpoint_id,
                    provider="local",
                    success=True,
                    duration_ms=2_500,
                )
            )
        await db.commit()

    response = app_client.get("/api/audiobook/settings/endpoint-stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["llm"][0]["answered"] == 0
    assert payload["tts"][0]["answered"] == 1
    assert payload["transcription"][0]["answered"] == 1


@pytest.mark.asyncio
async def test_tts_pool_test_api_returns_each_endpoint_result(
    app_client,
    sqlite_sessionmaker,
    monkeypatch,
):
    async with sqlite_sessionmaker() as db:
        db.add(
            models.AudiobookSettings(
                tts_endpoints=[
                    {"id": "qwen", "name": "Qwen", "provider": "qwen3", "base_url": "http://qwen"},
                    {"id": "omni", "name": "OmniVoice", "provider": "omnivoice", "base_url": "http://omni"},
                ]
            )
        )
        await db.commit()

    calls = []

    async def synthesize(endpoint_settings, _request):
        calls.append(endpoint_settings.tts_base_url)
        if endpoint_settings.tts_provider == "qwen3":
            raise RuntimeError("Qwen model is not loaded")
        return b"mp3"

    monkeypatch.setattr("backend.app.routers.audiobook._synthesize_speech_endpoint", synthesize)

    response = app_client.post("/api/audiobook/settings/test-tts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert payload["endpoint"] == "OmniVoice"
    assert calls == ["http://qwen", "http://omni"]
    assert payload["results"] == [
        {
            "endpoint_id": "qwen",
            "endpoint": "Qwen",
            "priority": 1,
            "provider": "qwen3",
            "model": None,
            "status": "error",
            "duration_ms": payload["results"][0]["duration_ms"],
            "error": "Qwen model is not loaded",
        },
        {
            "endpoint_id": "omni",
            "endpoint": "OmniVoice",
            "priority": 2,
            "provider": "omnivoice",
            "model": None,
            "status": "ready",
            "duration_ms": payload["results"][1]["duration_ms"],
            "error": None,
            "audio_bytes": 3,
        },
    ]
