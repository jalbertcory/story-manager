from types import SimpleNamespace

import pytest

from services.gpu_scheduler.docker_control import DockerController, MANAGED_LABEL, ORDER_LABEL


class FakeContainer:
    def __init__(self, name: str, status: str, order: int) -> None:
        self.id = f"{name}-container-id"
        self.name = name
        self.status = status
        self.labels = {MANAGED_LABEL: "true", ORDER_LABEL: str(order)}
        self.image = SimpleNamespace(tags=[f"example/{name}:latest"])
        self.attrs = {}
        self.stop_timeouts = []
        self.start_count = 0
        self.reload()

    def reload(self) -> None:
        self.attrs = {
            "State": {"Status": self.status, "Health": {"Status": "healthy"}},
            "Config": {"Image": f"example/{self.name}:latest"},
        }

    def start(self) -> None:
        self.start_count += 1
        self.status = "running"

    def stop(self, timeout: int) -> None:
        self.stop_timeouts.append(timeout)
        self.status = "exited"

    def unpause(self) -> None:
        self.status = "running"


class FakeCollection:
    def __init__(self, containers: list[FakeContainer]) -> None:
        self.containers = containers
        self.filters = None

    def list(self, *, all: bool, filters: dict):
        assert all is True
        self.filters = filters
        return self.containers


def controller_with(containers: list[FakeContainer]) -> tuple[DockerController, FakeCollection]:
    collection = FakeCollection(containers)
    controller = DockerController()
    controller._client = SimpleNamespace(containers=collection)
    return controller, collection


def test_controller_queries_only_opted_in_containers_and_starts_in_order():
    late = FakeContainer("late", "exited", 20)
    early = FakeContainer("early", "exited", 10)
    controller, collection = controller_with([late, early])

    snapshots, actions = controller.reconcile(True, 10)

    assert collection.filters == {"label": f"{MANAGED_LABEL}=true"}
    assert actions == ["Started early", "Started late"]
    assert [snapshot["name"] for snapshot in snapshots] == ["early", "late"]


def test_controller_stops_in_reverse_order_and_leaves_exited_container_alone():
    early = FakeContainer("early", "running", 10)
    late = FakeContainer("late", "running", 20)
    already_stopped = FakeContainer("stopped", "exited", 30)
    controller, _collection = controller_with([early, already_stopped, late])

    _snapshots, actions = controller.reconcile(False, 7)

    assert actions == ["Stopped late", "Stopped early"]
    assert late.stop_timeouts == [7]
    assert early.stop_timeouts == [7]
    assert already_stopped.stop_timeouts == []


def test_observe_only_never_changes_container_state():
    running = FakeContainer("running", "running", 10)
    stopped = FakeContainer("stopped", "exited", 20)
    controller, _collection = controller_with([running, stopped])

    snapshots, actions = controller.reconcile(None, 10)

    assert actions == []
    assert [snapshot["status"] for snapshot in snapshots] == ["running", "exited"]
    assert running.stop_timeouts == []
    assert stopped.start_count == 0


@pytest.mark.parametrize("field", ["id", "name"])
def test_incomplete_container_identity_reports_error_without_mutation(field):
    container = FakeContainer("incomplete", "running", 10)
    setattr(container, field, None)
    controller, _collection = controller_with([container])

    with pytest.raises(RuntimeError, match="Docker returned a container without"):
        controller.inspect()

    assert container.start_count == 0
    assert container.stop_timeouts == []
