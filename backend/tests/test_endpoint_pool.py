import httpx
import pytest

from backend.app import models
from backend.app.services import endpoint_pool


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
