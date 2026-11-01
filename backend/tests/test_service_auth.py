import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from services.service_auth import API_KEY_ENV, bearer_auth


def _client(*fallback_envs: str) -> TestClient:
    app = FastAPI(dependencies=[Depends(bearer_auth(*fallback_envs))])

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready"}

    @app.post("/generate")
    def generate() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.delenv("TRANSCRIPTION_API_KEY", raising=False)


def test_requests_are_unauthenticated_when_no_key_is_configured():
    client = _client()

    assert client.post("/generate").status_code == 200


def test_configured_key_is_required_for_every_endpoint_but_health(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(API_KEY_ENV, "s3cret")
    client = _client()

    missing = client.post("/generate")
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert client.post("/generate", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/generate", headers={"Authorization": "Basic s3cret"}).status_code == 401
    assert client.post("/generate", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.post("/generate", headers={"Authorization": "bearer s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200


def test_service_specific_key_is_a_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRANSCRIPTION_API_KEY", "legacy")
    client = _client("TRANSCRIPTION_API_KEY")

    assert client.post("/generate").status_code == 401
    assert client.post("/generate", headers={"Authorization": "Bearer legacy"}).status_code == 200

    monkeypatch.setenv(API_KEY_ENV, "shared")
    client = _client("TRANSCRIPTION_API_KEY")

    assert client.post("/generate", headers={"Authorization": "Bearer legacy"}).status_code == 401
    assert client.post("/generate", headers={"Authorization": "Bearer shared"}).status_code == 200
