"""Scheduler status, config, history routes and next-run calculation."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from backend.app import crud, models, schemas
from backend.app.services import update_scheduler, web_novel
from api_harness import AsyncTestingSessionLocal, client


@pytest.mark.asyncio
async def test_scheduler_status_empty(db_session):
    """
    Test GET /api/scheduler/status returns null when no tasks exist.
    """
    response = client.get("/api/scheduler/status")
    assert response.status_code == 200
    assert response.json() is None


def test_calculate_next_run_time_uses_last_run_plus_interval():
    now = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)
    last_run = now - timedelta(hours=6)

    next_run = update_scheduler.calculate_next_run_time(last_run, now=now)

    assert next_run == last_run + timedelta(hours=24)


def test_calculate_next_run_time_runs_soon_when_overdue():
    now = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)
    last_run = now - timedelta(hours=30)

    next_run = update_scheduler.calculate_next_run_time(last_run, now=now)

    assert next_run == now + update_scheduler.OVERDUE_RUN_DELAY


def test_get_last_run_anchor_prefers_start_for_failed_tasks():
    task = models.UpdateTask(status="failed", total_books=1, completed_books=1)
    task.started_at = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
    task.completed_at = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)

    anchor = update_scheduler.get_last_run_anchor(task)

    assert anchor == task.started_at


def test_get_next_run_time_for_interrupted_task_runs_soon():
    now = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)
    task = models.UpdateTask(status="interrupted", total_books=30, completed_books=14)
    task.started_at = now - timedelta(minutes=15)
    task.completed_at = now - timedelta(seconds=5)

    next_run = update_scheduler.get_next_run_time_for_task(task, now=now)

    assert next_run == now + update_scheduler.OVERDUE_RUN_DELAY


@pytest.mark.asyncio
async def test_scheduler_job_status(db_session, mocker):
    """
    Test GET /api/scheduler/job returns schedule metadata and latest run details.
    """
    async with AsyncTestingSessionLocal() as session:
        task = await crud.create_update_task(session, total_books=2)
        await crud.complete_update_task(session, task)

    class DummyJob:
        next_run_time = datetime(2026, 3, 20, 14, 30, tzinfo=timezone.utc)

    mocker.patch("backend.app.routers.scheduler.update_scheduler.get_scheduled_job", return_value=DummyJob())
    mocker.patch("backend.app.routers.scheduler.update_scheduler.is_scheduler_running", return_value=True)
    mocker.patch("backend.app.routers.scheduler.update_scheduler.is_update_running", return_value=False)

    response = client.get("/api/scheduler/job")

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "update_web_novels"
    assert data["schedule"] == "Every 24 hours"
    assert data["next_run_at"] == "2026-03-20T14:30:00Z"
    assert data["scheduler_running"] is True
    assert data["run_in_progress"] is False
    assert data["schedule_mode"] == "interval"
    assert data["schedule_time_local"] is None
    assert data["schedule_timezone"] is None
    assert data["last_run_status"] == "completed"
    assert data["last_run_started_at"] is not None
    assert data["last_run_completed_at"] is not None


@pytest.mark.asyncio
async def test_update_scheduler_config_persists_daily_time_and_reschedules(db_session, mocker):
    class DummyJob:
        next_run_time = datetime(2026, 3, 20, 10, 30, tzinfo=timezone.utc)

    schedule_mock = mocker.patch(
        "backend.app.routers.scheduler.update_scheduler.schedule_next_web_novel_update",
        return_value=DummyJob.next_run_time,
    )
    mocker.patch("backend.app.routers.scheduler.update_scheduler.get_scheduled_job", return_value=DummyJob())
    mocker.patch("backend.app.routers.scheduler.update_scheduler.is_scheduler_running", return_value=True)
    mocker.patch("backend.app.routers.scheduler.update_scheduler.is_update_running", return_value=False)

    response = client.put(
        "/api/scheduler/config",
        json={"time_local": "06:30", "timezone": "America/New_York"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["schedule"] == "Daily at 6:30 AM (America/New_York)"
    assert data["schedule_mode"] == "daily_time"
    assert data["schedule_time_local"] == "06:30"
    assert data["schedule_timezone"] == "America/New_York"
    assert data["next_run_at"] == "2026-03-20T10:30:00Z"
    schedule_mock.assert_awaited_once()

    async with AsyncTestingSessionLocal() as session:
        settings = await crud.get_scheduler_settings(session)
        assert settings is not None
        assert settings.web_novel_schedule_hour == 6
        assert settings.web_novel_schedule_minute == 30
        assert settings.web_novel_schedule_timezone == "America/New_York"


@pytest.mark.asyncio
async def test_update_web_novels_counts_and_logs_book_failures(db_session, mocker):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Broken Book A",
                author="Author",
                immutable_path="broken_a.epub",
                current_path="broken_a_current.epub",
                source_type=models.SourceType.web,
                source_url="https://example.com/broken-a",
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Broken Book B",
                author="Author",
                immutable_path="broken_b.epub",
                current_path="broken_b_current.epub",
                source_type=models.SourceType.web,
                source_url="https://example.com/broken-b",
            ),
        )

    mocker.patch("backend.app.services.web_novel.get_epub_word_and_chapter_count", return_value=(1000, 10))
    mocker.patch(
        "backend.app.services.web_novel.download_web_novel",
        side_effect=HTTPException(status_code=500, detail="boom"),
    )
    mocker.patch("backend.app.services.web_novel.SessionLocal", AsyncTestingSessionLocal)

    await web_novel.update_web_novels()

    async with AsyncTestingSessionLocal() as session:
        task = await crud.get_latest_update_task(session)
        assert task is not None
        assert task.total_books == 2
        assert task.completed_books == 2
        assert task.status == "failed"

        logs = await crud.get_book_logs_for_task(session, task.id)
        _, rows = logs
        assert rows is not None
        assert len(rows) == 2
        assert {row[0].entry_type for row in rows} == {"error"}


@pytest.mark.asyncio
async def test_scheduler_history_empty(db_session):
    """
    Test GET /api/scheduler/history returns empty list when no tasks exist.
    """
    response = client.get("/api/scheduler/history")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_scheduler_history_with_tasks(db_session):
    """
    Test GET /api/scheduler/history returns tasks ordered newest first.
    """
    async with AsyncTestingSessionLocal() as session:
        task1 = await crud.create_update_task(session, total_books=5)
        await crud.complete_update_task(session, task1)
        task2 = await crud.create_update_task(session, total_books=3)
        await crud.complete_update_task(session, task2)

    response = client.get("/api/scheduler/history")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {d["total_books"] for d in data} == {3, 5}
    assert all(d["status"] == "completed" for d in data)

    # Pagination works: limit=1 returns exactly 1 task
    r1 = client.get("/api/scheduler/history?limit=1")
    assert r1.status_code == 200
    assert len(r1.json()) == 1

    # offset=1 returns the other task
    r2 = client.get("/api/scheduler/history?limit=1&offset=1")
    assert r2.status_code == 200
    assert len(r2.json()) == 1
    assert r1.json()[0]["id"] != r2.json()[0]["id"]


@pytest.mark.asyncio
async def test_scheduler_history_task_logs(db_session):
    """
    Test GET /api/scheduler/history/{task_id}/logs returns per-book log entries.
    """
    async with AsyncTestingSessionLocal() as session:
        book_a = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Log Book A",
                author="Author",
                immutable_path="lba_i",
                current_path="lba_c",
                source_type=models.SourceType.web,
                source_url="http://example.com/lba",
            ),
        )
        book_b = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Log Book B",
                author="Author",
                immutable_path="lbb_i",
                current_path="lbb_c",
                source_type=models.SourceType.web,
                source_url="http://example.com/lbb",
            ),
        )
        task = await crud.create_update_task(session, total_books=2)
        await crud.create_book_log(
            session,
            schemas.BookLogCreate(
                book_id=book_a.id,
                entry_type="updated",
                previous_chapter_count=10,
                new_chapter_count=15,
                words_added=5000,
            ),
        )
        await crud.create_book_log(
            session,
            schemas.BookLogCreate(
                book_id=book_b.id,
                entry_type="checked",
                previous_chapter_count=8,
                new_chapter_count=8,
                words_added=0,
            ),
        )
        await crud.complete_update_task(session, task)

        response = client.get(f"/api/scheduler/history/{task.id}/logs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    titles = {entry["book_title"] for entry in data}
    assert titles == {"Log Book A", "Log Book B"}

    updated = next(e for e in data if e["entry_type"] == "updated")
    assert updated["book_title"] == "Log Book A"
    assert updated["previous_chapter_count"] == 10
    assert updated["new_chapter_count"] == 15
    assert updated["words_added"] == 5000

    checked = next(e for e in data if e["entry_type"] == "checked")
    assert checked["book_title"] == "Log Book B"
    assert checked["words_added"] == 0


@pytest.mark.asyncio
async def test_scheduler_history_task_logs_includes_error_entries(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Errored Book",
                author="Author",
                immutable_path="err_i",
                current_path="err_c",
                source_type=models.SourceType.web,
                source_url="http://example.com/err",
            ),
        )
        task = await crud.create_update_task(session, total_books=1)
        await crud.create_book_log(
            session,
            schemas.BookLogCreate(
                book_id=book.id,
                entry_type="error",
                previous_chapter_count=12,
                new_chapter_count=12,
                words_added=0,
            ),
        )
        await crud.fail_update_task(session, task)

    response = client.get(f"/api/scheduler/history/{task.id}/logs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["entry_type"] == "error"
    assert data[0]["book_title"] == "Errored Book"


@pytest.mark.asyncio
async def test_scheduler_history_task_logs_not_found(db_session):
    """
    Test GET /api/scheduler/history/{task_id}/logs returns 404 for unknown task.
    """
    response = client.get("/api/scheduler/history/9999/logs")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
