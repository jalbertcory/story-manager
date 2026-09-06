"""Operator-facing health, metrics, and safe diagnostic endpoints."""

from __future__ import annotations

from .. import api_schemas as contracts
import io
import json
import zipfile
from datetime import datetime, timezone

from fastapi import Response, APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..logging_config import redact_value
from ..services.observability import (
    diagnostic_configuration,
    diagnostic_logs,
    health_report,
    processing_job_metrics,
)
from ..services.processing_queue import get_processing_queue

router = APIRouter(prefix="/api/observability", tags=["observability"])


@router.get("/health", response_model=contracts.HealthReport)
async def get_health(db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    return await health_report(db, get_processing_queue())


@router.get("/ready", response_model=contracts.HealthReport)
async def get_readiness(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    report = await health_report(db, get_processing_queue())
    return JSONResponse(status_code=200 if report["status"] == "healthy" else 503, content=report)


@router.get("/job-metrics", response_model=contracts.JobMetrics)
async def get_job_metrics(
    window_hours: int = Query(default=24, ge=1, le=24 * 90),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await processing_job_metrics(db, window_hours=window_hours)


@router.get(
    "/diagnostics", response_model=None, response_class=Response, responses=contracts.media_responses("application/zip")
)
async def download_diagnostics(db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    """Download a redacted bundle with no library files, audio, or secret configuration."""
    queue = get_processing_queue()
    files = {
        "health.json": await health_report(db, queue),
        "job-metrics.json": await processing_job_metrics(db, window_hours=24),
        "logs.json": diagnostic_logs(),
        "configuration.json": diagnostic_configuration(),
        "manifest.json": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "redacted": True,
            "contents": ["health", "job metrics", "recent application logs", "configuration allowlist"],
        },
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, payload in files.items():
            archive.writestr(filename, json.dumps(redact_value(payload), indent=2, default=str))
    output.seek(0)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        output,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="story-manager-diagnostics-{timestamp}.zip"'},
    )
