"""Regression tests for health, metrics, correlation, and safe diagnostics."""

from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock, Mock

from backend.app.logging_config import _RedactedTextFormatter, read_persisted_logs, redact_text
from backend.app.models import ProcessingJob
from backend.app.services.observability import health_report, processing_job_metrics


def test_redact_text_removes_common_secret_forms():
    message = (
        "Authorization: Bearer private-token\n"
        "api_key=sk-secret postgresql+psycopg://story:password@database/story "
        '{"session_id": "browser-secret"}'
    )

    redacted = redact_text(message)

    assert "private-token" not in redacted
    assert "sk-secret" not in redacted
    assert "story:password" not in redacted
    assert "browser-secret" not in redacted
    assert redacted.count("[REDACTED]") >= 3


def test_persisted_logs_can_be_read_after_memory_is_gone(tmp_path):
    log_file = tmp_path / "story-manager.jsonl"
    entries = [
        {"timestamp": "2026-08-09T01:00:00+00:00", "level": "INFO", "message": "before restart"},
        {
            "timestamp": "2026-08-09T01:01:00+00:00",
            "level": "ERROR",
            "message": "api_key=do-not-show",
            "request_id": "request-123",
        },
    ]
    log_file.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")

    restored = read_persisted_logs(log_file=log_file)

    assert [entry["level"] for entry in restored] == ["INFO", "ERROR"]
    assert restored[0]["message"] == "before restart"
    assert "do-not-show" not in restored[1]["message"]
    assert restored[1]["request_id"] == "request-123"


def test_plain_console_formatter_redacts_interpolated_secrets():
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="request failed with api_key=%s",
        args=("console-secret",),
        exc_info=None,
    )

    output = _RedactedTextFormatter("%(message)s").format(record)

    assert "console-secret" not in output
    assert output == "request failed with api_key=[REDACTED]"


@pytest.mark.asyncio
async def test_processing_metrics_are_grouped_by_job_type(db):
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            ProcessingJob(
                job_type="clean_book",
                status="completed",
                request_id="metric-1",
                attempt_count=2,
                created_at=now - timedelta(minutes=3),
                started_at=now - timedelta(minutes=2),
                completed_at=now - timedelta(minutes=1),
            ),
            ProcessingJob(
                job_type="clean_book",
                status="error",
                request_id="metric-2",
                attempt_count=3,
                created_at=now - timedelta(minutes=4),
                started_at=now - timedelta(minutes=3),
                completed_at=now - timedelta(minutes=2),
            ),
            ProcessingJob(
                job_type="refresh_book",
                status="canceled",
                request_id="metric-3",
                created_at=now - timedelta(minutes=5),
            ),
        ]
    )
    await db.commit()

    result = await processing_job_metrics(db, window_hours=24)

    cleaning = result["by_job_type"]["clean_book"]
    assert cleaning == {
        "total": 2,
        "queued": 0,
        "running": 0,
        "completed": 1,
        "failed": 1,
        "canceled": 0,
        "retries": 3,
        "average_queue_delay_ms": 60000.0,
        "average_duration_ms": 60000.0,
    }
    assert result["by_job_type"]["refresh_book"]["canceled"] == 1


def test_request_ids_are_returned_and_can_be_supplied(app_client):
    generated = app_client.get("/health/live")
    supplied = app_client.get("/health/live", headers={"X-Request-ID": "browser-check-42"})
    unsafe = app_client.get("/health/live", headers={"X-Request-ID": "secret value\ninvalid"})

    assert len(generated.headers["X-Request-ID"]) == 12
    assert supplied.headers["X-Request-ID"] == "browser-check-42"
    assert unsafe.headers["X-Request-ID"] != "secret value\ninvalid"


@pytest.mark.asyncio
async def test_health_report_survives_database_outage():
    db = AsyncMock()
    db.execute.side_effect = RuntimeError("database unavailable")
    queue = Mock()
    queue.health_snapshot.return_value = {
        "status": "available",
        "running": True,
        "configured_workers": 1,
        "active_workers": 1,
        "failed_workers": 0,
        "lanes": {"maintenance": 1},
    }

    report = await health_report(db, queue)

    assert report["status"] == "unhealthy"
    assert report["database"] == {"status": "unavailable"}
    assert {provider["status"] for provider in report["providers"]} == {"unknown"}


def test_failure_details_include_request_id(app_client):
    response = app_client.get("/api/books/99999", headers={"X-Request-ID": "missing-book-7"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "missing-book-7"
    assert response.json()["request_id"] == "missing-book-7"


def test_health_metrics_and_redacted_diagnostics_are_available(app_client, monkeypatch):
    monkeypatch.setenv("STORY_MANAGER_AUTH_MODE", "disabled")
    monkeypatch.setenv("STORY_MANAGER_ADMIN_PASSWORD", "never-export-this")
    app_client.post(
        "/api/logs/client",
        headers={"X-Request-ID": "diagnostic-log-9"},
        json={"level": "ERROR", "message": "api_key=never-export-this", "source": "test"},
    )

    health = app_client.get("/api/observability/health")
    metrics = app_client.get("/api/observability/job-metrics")
    bundle = app_client.get("/api/observability/diagnostics")

    assert health.status_code == 200
    assert {"database", "workers", "storage", "providers"} <= health.json().keys()
    assert metrics.status_code == 200
    assert {"aggregate", "by_job_type", "window_hours"} <= metrics.json().keys()
    assert bundle.status_code == 200
    assert bundle.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert set(archive.namelist()) == {
            "health.json",
            "job-metrics.json",
            "logs.json",
            "configuration.json",
            "manifest.json",
        }
        combined = b"".join(archive.read(name) for name in archive.namelist())
    assert b"never-export-this" not in combined
    assert b"STORY_MANAGER_ADMIN_PASSWORD" not in combined


def test_application_logs_support_correlation_filtering(app_client):
    logging.getLogger("observability-test").error(
        "correlated test entry",
        extra={"request_id": "filter-me", "job_id": 481},
    )

    response = app_client.get("/api/logs?request_id=filter-me&job_id=481")

    assert response.status_code == 200
    assert any(entry["message"] == "correlated test entry" for entry in response.json())
