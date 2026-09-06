"""Exercise snapshots through reconciliation and the HTTP response contract."""

from fastapi.testclient import TestClient

from services.gpu_scheduler import server
from services.gpu_scheduler.docker_control import ContainerSnapshot


class Controller:
    def reconcile(self, available, timeout):
        return [ContainerSnapshot("abc", "tts", "running", None, 10, "tts:latest")], ["Started tts"]


def test_reconciled_state_has_typed_snapshots_and_preserves_wire_shape(tmp_path, monkeypatch):
    manager = server.AvailabilityManager(server.ConfigStore(tmp_path / "config.json"), Controller())
    monkeypatch.setattr(server, "manager", manager)
    client = TestClient(server.app)
    response = client.post("/api/reconcile")
    assert response.status_code == 200
    assert isinstance(manager.containers[0], ContainerSnapshot)
    assert response.json()["containers"] == [
        {"id": "abc", "name": "tts", "status": "running", "health": None, "order": 10, "image": "tts:latest"}
    ]
    assert response.json()["recent_actions"][0]["message"] == "Started tts"
    assert response.json()["next_transition"] is None
    assert response.json()["last_error"] is None
    assert response.json()["config"]["override_until"] is None
    assert client.get("/health").json() == {"status": "running", "docker_connected": True}


def test_scheduler_json_endpoints_have_concrete_response_models():
    document = server.app.openapi()
    for path in ("/api/state", "/api/config", "/api/override", "/api/reconcile", "/health"):
        for operation in document["paths"][path].values():
            schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
            model = document["components"]["schemas"][schema["$ref"].split("/")[-1]]
            assert model["properties"]
            assert set(model["required"]) == set(model["properties"])


def test_reconcile_failure_keeps_last_snapshot_and_exposes_error(tmp_path, monkeypatch):
    manager = server.AvailabilityManager(server.ConfigStore(tmp_path / "config.json"), Controller())
    monkeypatch.setattr(server, "manager", manager)
    client = TestClient(server.app)
    first = client.post("/api/reconcile").json()

    def fail(*_args):
        raise RuntimeError("Docker disconnected")

    monkeypatch.setattr(manager.controller, "reconcile", fail)
    second = client.post("/api/reconcile").json()
    assert second["containers"] == first["containers"]
    assert second["last_error"] == "Docker disconnected"
    assert client.get("/health").json()["docker_connected"] is False
