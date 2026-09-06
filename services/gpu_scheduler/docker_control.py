"""Narrow, label-scoped access to the Docker Engine."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from docker import DockerClient
    from docker.models.containers import Container

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


class _Health(BaseModel):
    model_config = ConfigDict(strict=True)
    Status: str | None = None


class _State(BaseModel):
    model_config = ConfigDict(strict=True)
    Status: str | None = None
    Health: _Health | None = None


class _Config(BaseModel):
    model_config = ConfigDict(strict=True)
    Image: str = "unknown"


class _Attributes(BaseModel):
    model_config = ConfigDict(strict=True)
    State: _State | None = None
    config: _Config = Field(default_factory=_Config, alias="Config")


class DockerController:
    """Start and stop only containers explicitly opted in through a label."""

    def __init__(self) -> None:
        self._client: DockerClient | None = None

    def _docker_client(self) -> DockerClient:
        if self._client is None:
            import docker

            self._client = docker.from_env(timeout=5)
        return self._client

    @staticmethod
    def _order(container: Container) -> int:
        raw = container.labels.get(ORDER_LABEL, "100")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 100

    @staticmethod
    def _name(container: Container) -> str:
        name = container.name
        if name is None:
            raise RuntimeError("Docker returned a container without a name.")
        return name

    def _managed_containers(self) -> list[Container]:
        containers = self._docker_client().containers.list(
            all=True,
            filters={"label": f"{MANAGED_LABEL}=true"},
        )
        return sorted(containers, key=lambda item: (self._order(item), self._name(item).casefold()))

    @classmethod
    def _snapshot(cls, container: Container) -> ContainerSnapshot:
        container.reload()
        attrs = _Attributes.model_validate(container.attrs)
        state = attrs.State or _State()
        health = state.Health.Status if state.Health else None
        tags = container.image.tags if container.image is not None else []
        identifier = container.id
        if identifier is None:
            raise RuntimeError("Docker returned a container without an ID.")
        return ContainerSnapshot(
            id=identifier[:12],
            name=cls._name(container),
            status=state.Status or container.status,
            health=health,
            order=cls._order(container),
            image=tags[0] if tags else attrs.config.Image,
        )

    def inspect(self) -> list[ContainerSnapshot]:
        return [self._snapshot(container) for container in self._managed_containers()]

    def reconcile(self, available: bool | None, stop_timeout_seconds: int) -> tuple[list[ContainerSnapshot], list[str]]:
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

        return [self._snapshot(container) for container in containers], actions
