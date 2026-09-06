"""Sanitized health reports, processing metrics, and diagnostic exports."""

from __future__ import annotations

import os
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from .. import api_schemas as contracts

from ..log_types import LogEntry

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..logging_config import read_persisted_logs, redact_text
from ..models import ProcessingJob
from .endpoint_pool import configured_endpoints
from .processing_queue import ProcessingQueue


@overload
def _aware(value: datetime) -> datetime: ...


@overload
def _aware(value: None) -> None: ...


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


async def processing_job_metrics(db: AsyncSession, *, window_hours: int = 24) -> contracts.JobMetrics:
    """Summarize queue delay, runtime, retries, cancellation, and failures."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)
    jobs = list(
        (
            await db.scalars(
                select(ProcessingJob).where(ProcessingJob.created_at >= cutoff).order_by(ProcessingJob.created_at.desc())
            )
        ).all()
    )
    grouped: dict[str, list[ProcessingJob]] = defaultdict(list)
    for job in jobs:
        grouped[job.job_type].append(job)

    def summarize(rows: list[ProcessingJob]) -> contracts.JobMetricSummary:
        queue_delays = [
            max(0.0, ((_aware(row.started_at) - _aware(row.created_at)).total_seconds() * 1000))
            for row in rows
            if row.started_at and row.created_at
        ]
        durations = [
            max(0.0, ((_aware(row.completed_at) - _aware(row.started_at)).total_seconds() * 1000))
            for row in rows
            if row.completed_at and row.started_at
        ]
        statuses: defaultdict[str, int] = defaultdict(int)
        for row in rows:
            statuses[row.status] += 1
        return {
            "total": len(rows),
            "queued": statuses["queued"],
            "running": statuses["running"],
            "completed": statuses["completed"],
            "failed": statuses["error"],
            "canceled": statuses["canceled"],
            "retries": sum(max(0, row.attempt_count - 1) for row in rows),
            "average_queue_delay_ms": _average(queue_delays),
            "average_duration_ms": _average(durations),
        }

    return {
        "generated_at": now.isoformat(),
        "window_hours": window_hours,
        "aggregate": summarize(jobs),
        "by_job_type": {job_type: summarize(rows) for job_type, rows in sorted(grouped.items())},
    }


def storage_health(path: Path = LIBRARY_PATH) -> contracts.StorageHealth:
    """Report capacity and writability without exposing the host path."""
    target = path if path.exists() else path.parent
    try:
        usage = shutil.disk_usage(target)
        percent_free = round((usage.free / usage.total) * 100, 1) if usage.total else 0.0
        minimum_bytes = max(0, int(os.getenv("STORY_MANAGER_MIN_FREE_BYTES", str(1024**3))))
        writable = os.access(target, os.W_OK)
        low_capacity = usage.free < minimum_bytes or percent_free < 5
        return {
            "status": "available" if writable and not low_capacity else "unavailable",
            "writable": writable,
            "total_bytes": usage.total,
            "free_bytes": usage.free,
            "percent_free": percent_free,
            "minimum_free_bytes": minimum_bytes,
        }
    except OSError:
        return {"status": "unavailable", "writable": False}


async def provider_health(db: AsyncSession) -> list[contracts.ProviderHealth]:
    """Describe optional provider configuration without returning secrets or URLs."""
    settings = await crud.audiobook.get_audiobook_settings(db)
    providers: list[contracts.ProviderHealth] = []
    for capability in ("llm", "tts", "transcription"):
        endpoints = configured_endpoints(settings, capability) if settings else []
        enabled = [
            endpoint for endpoint in endpoints if str(endpoint.provider or "").strip().lower() not in {"", "disabled", "none"}
        ]
        providers.append(
            {
                "capability": capability,
                "status": "configured" if enabled else "disabled",
                "configured_endpoints": len(enabled),
            }
        )
    return providers


def _unknown_providers() -> list[contracts.ProviderHealth]:
    return [
        {"capability": capability, "status": "unknown", "configured_endpoints": 0}
        for capability in ("llm", "tts", "transcription")
    ]


async def health_report(db: AsyncSession, queue: ProcessingQueue) -> contracts.HealthReport:
    database: contracts.StatusResponse = {"status": "available"}
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        database = {"status": "unavailable"}
    providers = _unknown_providers()
    if database["status"] == "available":
        try:
            providers = await provider_health(db)
        except Exception:
            providers = _unknown_providers()
    workers = queue.health_snapshot()
    storage = storage_health()
    required = (database["status"], workers["status"], storage["status"])
    return {
        "status": "healthy" if all(status == "available" for status in required) else "unhealthy",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "liveness": {"status": "alive"},
        "database": database,
        "workers": workers,
        "storage": storage,
        "providers": providers,
    }


def diagnostic_configuration() -> dict[str, str]:
    """Return an explicit allowlist of non-secret runtime configuration."""
    names = (
        "LOG_FORMAT",
        "STORY_MANAGER_LOG_MAX_BYTES",
        "STORY_MANAGER_LOG_BACKUP_COUNT",
        "STORY_MANAGER_MIN_FREE_BYTES",
        "RECYCLE_BIN_RETENTION_DAYS",
        "PROCESSING_LEASE_SECONDS",
        "PROCESSING_HEARTBEAT_SECONDS",
        "PROCESSING_POLL_SECONDS",
        "PROCESSING_RETRY_BACKOFF_SECONDS",
        "PROCESSING_CPU_CONCURRENCY",
        "PROCESSING_MAINTENANCE_CONCURRENCY",
        "PROCESSING_LLM_CONCURRENCY",
        "PROCESSING_TTS_CONCURRENCY",
        "PROCESSING_TRANSCRIPTION_CONCURRENCY",
    )
    return {name: redact_text(os.getenv(name, "default")) for name in names}


def diagnostic_logs(limit: int = 500) -> list[LogEntry]:
    """Read the bounded, already-redacted recent application log history."""
    return read_persisted_logs(limit=limit)
