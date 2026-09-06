"""Regression coverage for endpoint secrets and atomic revision restoration."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app import models
from backend.app.routers import audiobook
from backend.app.services.book_recovery import restore_snapshot, snapshot_book
from backend.app.services.endpoint_pool import configured_endpoints, route_request


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, "saved-key"),
        ({"api_key": None}, None),
        ({"api_key": ""}, None),
        ({"api_key": "new-key"}, "new-key"),
        ({"provider": "different"}, None),
        ({"provider": "different", "api_key": "new-key"}, "new-key"),
        ({"provider": " OLLAMA "}, "saved-key"),
    ],
)
@pytest.mark.asyncio
async def test_endpoint_secret_intent_survives_validation_and_storage(db, changes, expected):
    settings = models.AudiobookSettings(
        llm_endpoints=[
            {
                "id": "host",
                "name": "Host",
                "provider": "ollama",
                "api_key": "saved-key",
            }
        ]
    )
    db.add(settings)
    await db.commit()
    update = audiobook.EndpointUpdate.model_validate(
        {
            "id": "host",
            "name": "Host",
            "provider": "ollama",
            **changes,
        }
    )
    response = await audiobook.update_settings(audiobook.SettingsUpdate(llm_endpoints=[update]), db)
    await db.refresh(settings)
    assert settings.llm_endpoints[0]["api_key"] == expected
    assert settings.llm_api_key == expected
    assert response.llm_endpoints[0].api_key_set == bool(expected)
    assert "api_key" not in response.llm_endpoints[0].model_dump()


def test_legacy_endpoint_columns_and_optional_fields_remain_supported():
    settings = models.AudiobookSettings(llm_provider="ollama", llm_base_url="http://old-host", llm_api_key="secret")
    endpoint = configured_endpoints(settings, "llm")[0]
    assert endpoint.id == "legacy-llm"
    assert endpoint.api_key == "secret"
    assert "secret" not in repr(endpoint)
    settings.llm_endpoints = [{"provider": "ollama", "legacy_extra": True}]
    endpoint = configured_endpoints(settings, "llm")[0]
    assert endpoint.model is None
    assert endpoint.provider == "ollama"


@pytest.mark.asyncio
async def test_invalid_stored_endpoint_never_reaches_provider():
    settings = models.AudiobookSettings(llm_endpoints=[{"provider": "ollama", "api_key": False}])
    attempt = AsyncMock()
    with pytest.raises(ValidationError):
        await route_request(settings, "llm", attempt)
    attempt.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoints",
    [
        None,
        [{"id": "same", "name": "A", "provider": "ollama"}, {"id": "same", "name": "B", "provider": "ollama"}],
        [{"id": "host", "name": "Host", "provider": "ollama", "api_key": False}],
    ],
)
async def test_bad_endpoint_updates_do_not_change_settings(app_client, sqlite_sessionmaker, endpoints):
    async with sqlite_sessionmaker() as db:
        settings = models.AudiobookSettings(llm_api_key="saved-key")
        db.add(settings)
        await db.commit()
        settings_id = settings.id
    response = app_client.put("/api/audiobook/settings", json={"llm_endpoints": endpoints})
    assert response.status_code == 422
    async with sqlite_sessionmaker() as db:
        settings = await db.get(models.AudiobookSettings, settings_id)
        assert settings.llm_api_key == "saved-key"
        assert settings.llm_endpoints is None


def test_snapshot_round_trip_retains_json_shape_and_nullable_values():
    timestamp = datetime(2026, 9, 6, tzinfo=timezone.utc)
    book = models.Book(
        title="Before",
        series_index=Decimal("2.50"),
        audiobook_enabled=False,
        metadata_synced_at=timestamp,
        metadata_remote_ids={"isbn": "123"},
        removed_chapters=["one.xhtml"],
    )
    snapshot = snapshot_book(book)
    assert snapshot["series_index"] == 2.5
    assert snapshot["author"] is None
    restore_snapshot(book, {**snapshot, "title": "After"})
    assert book.title == "After"
    assert book.series_index == Decimal("2.5")
    assert book.metadata_synced_at == timestamp
    assert book.removed_chapters == ["one.xhtml"]


def test_partial_old_snapshot_preserves_omitted_fields_and_ignores_unknown_fields():
    book = models.Book(title="Current", author="Author", notes="Notes", audiobook_enabled=True)
    restore_snapshot(book, {"title": "Old", "notes": None, "future_field": "ignored"})
    assert book.title == "Old"
    assert book.notes is None
    assert book.author == "Author"
    assert book.audiobook_enabled is True


@pytest.mark.parametrize(
    "invalid",
    [
        {"metadata_synced_at": "not a date"},
        {"audiobook_enabled": "false"},
        {"audiobook_enabled": None},
        {"removed_chapters": [7]},
        {"series_index": True},
        {"series_index": float("inf")},
        {"series_index": 10000},
        {"metadata_remote_ids": ["bad"]},
    ],
)
def test_whole_snapshot_is_validated_before_any_orm_assignment(invalid):
    book = models.Book(title="Current", author="Author", audiobook_enabled=True)
    with pytest.raises(ValidationError):
        restore_snapshot(book, {"title": "Must not apply", **invalid})
    assert book.title == "Current"
    assert book.author == "Author"
    assert book.audiobook_enabled is True


@pytest.mark.asyncio
async def test_invalid_revision_is_inspectable_but_restore_creates_no_changes(app_client, sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        book = models.Book(title="Current", author="Author", audiobook_enabled=True)
        db.add(book)
        await db.flush()
        revision = models.BookRevision(
            book_id=book.id,
            action="metadata_changed",
            summary="Old revision",
            snapshot={"title": "Must not apply", "audiobook_enabled": "false"},
        )
        db.add(revision)
        await db.commit()
        book_id, revision_id = book.id, revision.id
    assert app_client.get(f"/api/books/{book_id}/revisions").status_code == 200
    response = app_client.post(f"/api/books/{book_id}/revisions/{revision_id}/restore")
    assert response.status_code == 422
    async with sqlite_sessionmaker() as db:
        book = await db.get(models.Book, book_id)
        assert book.title == "Current"
        assert book.audiobook_enabled is True
        assert await db.scalar(select(func.count(models.BookRevision.id))) == 1
        assert await db.scalar(select(func.count(models.ProcessingJob.id))) == 0
