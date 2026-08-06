"""FastAPI control panel for scheduled GPU-container availability."""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .docker_control import DockerController, MANAGED_LABEL
from .domain import OverrideRequest, SchedulerConfig, effective_availability, next_policy_transition

logger = logging.getLogger(__name__)

DATA_PATH = Path(os.getenv("SCHEDULER_DATA_PATH", "/data/config.json"))
RECONCILE_SECONDS = max(5, int(os.getenv("SCHEDULER_RECONCILE_SECONDS", "15")))
STATIC_DIR = Path(__file__).with_name("static")


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._config = self._load()

    def _load(self) -> SchedulerConfig:
        if not self.path.exists():
            return SchedulerConfig()
        try:
            return SchedulerConfig.model_validate_json(self.path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Ignoring invalid GPU scheduler configuration at %s", self.path)
            return SchedulerConfig()

    @property
    def config(self) -> SchedulerConfig:
        return self._config.model_copy(deep=True)

    def save(self, config: SchedulerConfig) -> SchedulerConfig:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(config.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.path)
        self._config = config.model_copy(deep=True)
        return self.config


class AvailabilityManager:
    def __init__(self, store: ConfigStore, controller: DockerController) -> None:
        self.store = store
        self.controller = controller
        self.containers: list[dict[str, Any]] = []
        self.last_error: str | None = None
        self.last_reconciled_at: datetime | None = None
        self.actions: deque[dict[str, str]] = deque(maxlen=20)
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()

    def wake(self) -> None:
        self._wake.set()

    def _expire_override(self, config: SchedulerConfig, now: datetime) -> SchedulerConfig:
        if config.override_mode != "automatic" and config.override_until is not None and now >= config.override_until:
            config.override_mode = "automatic"
            config.override_until = None
            return self.store.save(config)
        return config

    async def reconcile(self) -> None:
        async with self._lock:
            now = datetime.now(timezone.utc)
            config = self._expire_override(self.store.config, now)
            desired, _source = effective_availability(config, now)
            try:
                containers, actions = await asyncio.to_thread(
                    self.controller.reconcile,
                    desired,
                    config.stop_timeout_seconds,
                )
                self.containers = containers
                self.last_error = None
                for action in actions:
                    self.actions.appendleft({"at": now.isoformat(), "message": action})
            except Exception as exc:
                logger.warning("GPU container reconciliation failed: %s", exc)
                self.last_error = str(exc)
            self.last_reconciled_at = now

    async def run(self) -> None:
        while True:
            await self.reconcile()
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=RECONCILE_SECONDS)
            except TimeoutError:
                pass

    def state(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        config = self.store.config
        desired, source = effective_availability(config, now)
        transition = next_policy_transition(config, now)
        return {
            "config": json.loads(config.model_dump_json()),
            "desired_available": desired,
            "policy_source": source,
            "next_transition": transition.isoformat() if transition else None,
            "containers": self.containers,
            "managed_label": f"{MANAGED_LABEL}=true",
            "last_error": self.last_error,
            "last_reconciled_at": self.last_reconciled_at.isoformat() if self.last_reconciled_at else None,
            "recent_actions": list(self.actions),
        }


store = ConfigStore(DATA_PATH)
manager = AvailabilityManager(store, DockerController())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(manager.run())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Story Manager GPU Availability", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "running", "docker_connected": manager.last_error is None}


@app.get("/api/state")
async def state() -> dict[str, Any]:
    return manager.state()


@app.put("/api/config")
async def update_config(config: SchedulerConfig) -> dict[str, Any]:
    current = store.config
    config.override_mode = current.override_mode
    config.override_until = current.override_until
    store.save(config)
    await manager.reconcile()
    manager.wake()
    return manager.state()


@app.post("/api/override")
async def update_override(request: OverrideRequest) -> dict[str, Any]:
    config = store.config
    config.override_mode = request.mode
    if request.mode == "automatic":
        config.override_until = None
    elif request.duration_minutes is None:
        config.override_until = None
    else:
        config.override_until = datetime.now(timezone.utc) + timedelta(minutes=request.duration_minutes)
    store.save(config)
    await manager.reconcile()
    manager.wake()
    return manager.state()


@app.post("/api/reconcile")
async def reconcile() -> dict[str, Any]:
    await manager.reconcile()
    return manager.state()


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
