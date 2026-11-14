"""Outbound webhook notifications: formats, API, queueing and delivery."""

from types import SimpleNamespace

import pytest
import requests
from sqlalchemy import select

from backend.app import crud, models
from backend.app.services import notifications
from backend.app.services.processing_queue import ProcessingQueue

SECRET_URL = "https://discord.example/api/webhooks/123/super-secret-token"


def test_request_bodies_match_each_receiver_format():
    kwargs = {"event": "job_failed", "title": "Backup failed", "message": "disk full"}
    generic = notifications.build_webhook_request("json", **kwargs)
    assert generic.json_body is not None
    assert {key: generic.json_body[key] for key in ("event", "title", "message")} == kwargs
    assert notifications.build_webhook_request("discord", **kwargs).json_body == {"content": "**Backup failed**\ndisk full"}
    assert notifications.build_webhook_request("slack", **kwargs).json_body == {"text": "*Backup failed*\ndisk full"}
    ntfy = notifications.build_webhook_request("ntfy", **kwargs)
    assert ntfy.text_body == "disk full"
    assert ntfy.headers["Title"] == "Backup failed"


def test_ntfy_title_with_non_ascii_text_is_a_valid_header():
    request = notifications.build_webhook_request("ntfy", event="new_chapters", title="Nové kapitoly\n✨", message="")
    assert request.headers["Title"].startswith("=?UTF-8?B?")
    request.headers["Title"].encode("latin-1")
    assert request.text_body == "Nové kapitoly\n✨"


@pytest.mark.parametrize("url", ["ftp://example.com/x", "example.com/hook", "file:///etc/passwd", "https://"])
def test_only_http_urls_are_accepted(url):
    with pytest.raises(ValueError):
        notifications.validate_webhook_url(url)


def test_delivery_errors_never_contain_the_webhook_url(mocker):
    mocker.patch.object(
        notifications.requests,
        "post",
        side_effect=requests.ConnectionError(f"Max retries exceeded with url: {SECRET_URL}"),
    )
    with pytest.raises(notifications.WebhookDeliveryError) as excinfo:
        notifications.send_webhook(SECRET_URL, "discord", event="test", title="t", message="m")
    assert "secret" not in str(excinfo.value)


def test_redirects_are_not_followed_and_error_statuses_fail(mocker):
    post = mocker.patch.object(notifications.requests, "post", return_value=SimpleNamespace(status_code=302))
    with pytest.raises(notifications.WebhookDeliveryError, match="HTTP 302"):
        notifications.send_webhook(SECRET_URL, "json", event="test", title="t", message="m")
    assert post.call_args.kwargs["allow_redirects"] is False


def test_webhook_api_hides_the_url_and_validates_input(app_client):
    created = app_client.post(
        "/api/notifications/webhooks",
        json={"name": " Phone ", "url": SECRET_URL, "format": "discord", "events": ["job_failed", "job_failed"]},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Phone"
    assert body["url_preview"] == "https://discord.example/…"
    assert "super-secret-token" not in created.text
    assert body["events"] == ["job_failed"]

    listed = app_client.get("/api/notifications/webhooks")
    assert [item["id"] for item in listed.json()] == [body["id"]]
    assert "super-secret-token" not in listed.text

    patched = app_client.patch(f"/api/notifications/webhooks/{body['id']}", json={"enabled": False})
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert patched.json()["events"] == ["job_failed"]

    assert app_client.post("/api/notifications/webhooks", json={"name": "x", "url": "ftp://x"}).status_code == 422
    assert (
        app_client.post("/api/notifications/webhooks", json={"name": "x", "url": SECRET_URL, "events": ["nope"]}).status_code
        == 422
    )
    assert app_client.delete(f"/api/notifications/webhooks/{body['id']}").status_code == 204
    assert app_client.delete(f"/api/notifications/webhooks/{body['id']}").status_code == 404


@pytest.mark.asyncio
async def test_emit_queues_one_job_per_subscribed_enabled_webhook(db, sqlite_sessionmaker, monkeypatch):
    monkeypatch.setattr(notifications, "SessionLocal", sqlite_sessionmaker)
    subscribed = await crud.create_notification_webhook(
        db, name="A", url=SECRET_URL, format="discord", events=["job_failed"], enabled=True
    )
    await crud.create_notification_webhook(
        db, name="B", url=SECRET_URL, format="discord", events=["new_chapters"], enabled=True
    )
    await crud.create_notification_webhook(
        db, name="C", url=SECRET_URL, format="discord", events=["job_failed"], enabled=False
    )

    assert await notifications.emit_notification("job_failed", "Backup failed", "disk full") == 1

    jobs = list((await db.execute(select(models.ProcessingJob))).scalars().all())
    assert [(job.job_type, job.target_id, job.resource_lane) for job in jobs] == [
        ("deliver_notification", subscribed.id, "maintenance")
    ]
    assert jobs[0].payload == {"event": "job_failed", "title": "Backup failed", "message": "disk full"}
    assert SECRET_URL not in str(jobs[0].payload)


@pytest.mark.asyncio
async def test_emit_without_webhooks_queues_nothing(db, sqlite_sessionmaker, monkeypatch):
    monkeypatch.setattr(notifications, "SessionLocal", sqlite_sessionmaker)
    assert await notifications.emit_notification("job_failed", "x") == 0
    assert (await db.execute(select(models.ProcessingJob))).first() is None


@pytest.mark.asyncio
async def test_delivery_records_the_outcome_on_the_webhook(db, sqlite_sessionmaker, monkeypatch, mocker):
    monkeypatch.setattr(notifications, "SessionLocal", sqlite_sessionmaker)
    webhook = await crud.create_notification_webhook(
        db, name="Phone", url="https://ntfy.example/topic", format="ntfy", events=["job_failed"], enabled=True
    )
    post = mocker.patch.object(notifications.requests, "post", return_value=SimpleNamespace(status_code=200))

    detail = await notifications.deliver_to_webhook(webhook.id, event="job_failed", title="Failed", message="why")
    assert detail == "Notification sent to Phone"
    assert post.call_args.args[0] == "https://ntfy.example/topic"
    assert post.call_args.kwargs["data"] == b"why"
    await db.refresh(webhook)
    assert (webhook.last_delivery_status, webhook.last_delivery_error) == ("ok", None)

    post.return_value = SimpleNamespace(status_code=500)
    with pytest.raises(notifications.WebhookDeliveryError):
        await notifications.deliver_to_webhook(webhook.id, event="job_failed", title="Failed", message="why")
    await db.refresh(webhook)
    assert webhook.last_delivery_status == "error"
    assert "HTTP 500" in (webhook.last_delivery_error or "")

    assert "deleted" in await notifications.deliver_to_webhook(9999, event="job_failed", title="x", message="")


@pytest.mark.asyncio
async def test_final_job_failure_is_announced_but_retries_and_delivery_failures_are_not(mocker):
    from backend.app.services import processing_queue

    emit = mocker.patch.object(processing_queue, "emit_notification", mocker.AsyncMock(return_value=0))
    session = mocker.MagicMock()
    session.__aenter__ = mocker.AsyncMock(return_value=session)
    session.__aexit__ = mocker.AsyncMock(return_value=False)
    mocker.patch.object(processing_queue, "SessionLocal", return_value=session)
    fail = mocker.patch.object(processing_queue.crud, "fail_processing_job", mocker.AsyncMock())
    queue = ProcessingQueue()
    mocker.patch.object(queue, "_execute_with_heartbeat", mocker.AsyncMock(side_effect=RuntimeError("disk full")))

    backup = SimpleNamespace(id=1, job_type="create_backup", book_id=None)
    fail.return_value = "queued"
    await queue._process_claimed_job(backup, "owner")
    emit.assert_not_awaited()

    fail.return_value = "error"
    await queue._process_claimed_job(backup, "owner")
    emit.assert_awaited_once_with("job_failed", "Background job failed: create backup", "disk full", book_id=None)

    emit.reset_mock()
    await queue._process_claimed_job(SimpleNamespace(id=2, job_type="deliver_notification", book_id=None), "owner")
    emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_run_summary_lists_books_with_new_chapters(db, mocker):
    from backend.app import schemas
    from backend.app.services import processing_queue

    emit = mocker.patch.object(processing_queue, "emit_notification", mocker.AsyncMock(return_value=0))
    task = models.UpdateTask(status="completed", total_books=2, completed_books=2)
    db.add(task)
    await db.commit()
    queue = ProcessingQueue()

    await queue._announce_new_chapters(db, task.id)
    emit.assert_not_awaited()

    book = await crud.create_book(db, schemas.BookCreate(title="The Long Road", author="A", source_type=models.SourceType.web))
    quiet = await crud.create_book(db, schemas.BookCreate(title="Quiet", author="A", source_type=models.SourceType.web))
    db.add_all(
        [
            models.BookLog(
                book_id=book.id,
                entry_type="updated",
                previous_chapter_count=10,
                new_chapter_count=13,
                words_added=4200,
                update_task_id=task.id,
            ),
            models.BookLog(book_id=quiet.id, entry_type="checked", update_task_id=task.id),
        ]
    )
    await db.commit()

    await queue._announce_new_chapters(db, task.id)
    emit.assert_awaited_once_with("new_chapters", "1 story has new chapters", "The Long Road: 3 new chapters, 4,200 words")


def test_invalid_port_is_rejected_before_anything_is_stored(app_client):
    response = app_client.post("/api/notifications/webhooks", json={"name": "x", "url": "https://example.com:99999/topic"})
    assert response.status_code == 422
    assert app_client.get("/api/notifications/webhooks").json() == []
    assert notifications.webhook_url_preview("https://example.com:99999/topic") == "https://example.com/…"


@pytest.mark.asyncio
async def test_queued_delivery_is_skipped_once_paused_or_unsubscribed_but_tests_still_send(
    db, sqlite_sessionmaker, monkeypatch, mocker
):
    monkeypatch.setattr(notifications, "SessionLocal", sqlite_sessionmaker)
    post = mocker.patch.object(notifications.requests, "post", return_value=SimpleNamespace(status_code=200))
    webhook = await crud.create_notification_webhook(
        db, name="Phone", url=SECRET_URL, format="discord", events=["job_failed"], enabled=True
    )

    detail = await notifications.deliver_to_webhook(webhook.id, event="new_chapters", title="t", message="m")
    assert "no longer subscribes" in detail
    await crud.update_notification_webhook(db, webhook, enabled=False)
    detail = await notifications.deliver_to_webhook(webhook.id, event="job_failed", title="t", message="m")
    assert "paused" in detail
    post.assert_not_called()

    await notifications.deliver_to_webhook(webhook.id, event="test", title="t", message="m", require_subscription=False)
    post.assert_called_once()
