"""Narrow, label-scoped access to the Docker Engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from typing import Any

MANAGED_LABEL = "story-manager.gpu-scheduler.managed"
ORDER_LABEL = "story-manager.gpu-scheduler.order"

logger = logging.getLogger(__name__)


@dataclass
class ContainerSnapshot:
    id: str
    name: str
    status: str
    health: str | None
    order: int
    image: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DockerController:
    """Start and stop only containers explicitly opted in through a label."""

    def __init__(self) -> None:
        self._client = None

    def _docker_client(self):
        if self._client is None:
            import docker

            self._client = docker.from_env(timeout=5)
        return self._client

    @staticmethod
    def _order(container) -> int:
        raw = container.labels.get(ORDER_LABEL, "100")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 100

    def _managed_containers(self):
        containers = self._docker_client().containers.list(
            all=True,
            filters={"label": f"{MANAGED_LABEL}=true"},
        )
        return sorted(containers, key=lambda item: (self._order(item), item.name.casefold()))

    @classmethod
    def _snapshot(cls, container) -> ContainerSnapshot:
        container.reload()
        state = container.attrs.get("State") or {}
        health = (state.get("Health") or {}).get("Status")
        tags = container.image.tags if container.image is not None else []
        return ContainerSnapshot(
            id=container.id[:12],
            name=container.name,
            status=state.get("Status") or container.status,
            health=health,
            order=cls._order(container),
            image=tags[0] if tags else container.attrs.get("Config", {}).get("Image", "unknown"),
        )

    def inspect(self) -> list[dict[str, Any]]:
        return [self._snapshot(container).to_dict() for container in self._managed_containers()]

    def reconcile(self, available: bool | None, stop_timeout_seconds: int) -> tuple[list[dict[str, Any]], list[str]]:
        containers = self._managed_containers()
        actions: list[str] = []

        if available is True:
            for container in containers:
                container.reload()
                if container.status != "running":
                    container.start()
                    actions.append(f"Started {container.name}")
        elif available is False:
            for container in reversed(containers):
                container.reload()
                if container.status == "paused":
                    container.unpause()
                    container.reload()
                if container.status in {"running", "restarting"}:
                    container.stop(timeout=stop_timeout_seconds)
                    actions.append(f"Stopped {container.name}")

        return [self._snapshot(container).to_dict() for container in containers], actions
