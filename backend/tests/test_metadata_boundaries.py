"""Malformed stored metadata must not change books or expand job scope."""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app import crud, models, schemas
from backend.app.metadata_types import MetadataJobScope, metadata_details, remote_identifiers
from backend.app.services.metadata.scoring import score_metadata_candidate, series_match_issues
from backend.app.services.metadata_jobs import (
    approve_metadata_match,
    create_metadata_sync_job_request,
    process_metadata_sync_job,
)
from backend.app.services.metadata_sync import MetadataSuggestion, apply_suggestion_to_book


@pytest.mark.parametrize(
    "scope",
    [
        {"book_ids": "1"},
        {"book_ids": ["1"]},
        {"book_ids": [True]},
        {"book_ids": [0]},
        {"book_ids": [-1]},
        {"book_ids": [1.5]},
        {"book_ids": None},
        {"book_ids": [1], "all_books": True},
        [],
    ],
)
@pytest.mark.asyncio
async def test_invalid_persisted_job_scope_fails_before_loading_books(db, mocker, scope):
    job = models.MetadataSyncJob(trigger="manual", status="queued", scope=scope)
    db.add(job)
    await db.commit()
    get_targets = mocker.patch("backend.app.crud.get_books_by_ids")
    get_library = mocker.patch("backend.app.crud.get_books")
    generate = mocker.patch("backend.app.services.metadata_jobs.generate_candidate_suggestions")

    await process_metadata_sync_job(db, job.id)

    assert job.status == "failed"
    assert job.processed_books == 0
    assert job.error
    get_targets.assert_not_called()
    get_library.assert_not_called()
    generate.assert_not_called()


@pytest.mark.parametrize("scope", [None, {}, {"book_ids": []}])
@pytest.mark.asyncio
async def test_legacy_empty_job_scopes_remain_empty(db, mocker, scope):
    job = models.MetadataSyncJob(trigger="manual", status="queued", scope=scope)
    db.add(job)
    await db.commit()
    get_targets = mocker.patch("backend.app.crud.get_books_by_ids", return_value=[])
    mocker.patch("backend.app.crud.get_books", return_value=[])
    generate = mocker.patch("backend.app.services.metadata_jobs.generate_candidate_suggestions")

    await process_metadata_sync_job(db, job.id)

    assert job.status == "completed"
    get_targets.assert_awaited_once_with(db, [])
    generate.assert_not_called()


@pytest.mark.asyncio
async def test_scope_is_validated_at_enqueue_and_deduplicated(db):
    with pytest.raises(ValidationError):
        await crud.create_metadata_sync_job(db, trigger="manual", book_ids=[True])
    assert await db.scalar(select(func.count()).select_from(models.MetadataSyncJob)) == 0

    job = await crud.create_metadata_sync_job(db, trigger="manual", book_ids=[2, 1, 2])
    assert job.scope == {"book_ids": [2, 1]}
    assert job.total_books == 2
    assert MetadataJobScope.model_validate(job.scope).book_ids == [2, 1]


@pytest.mark.asyncio
async def test_empty_requested_scope_does_not_select_whole_library(db, mocker):
    get_library = mocker.patch("backend.app.crud.get_books")
    get_targets = mocker.patch("backend.app.crud.get_books_by_ids", return_value=[])
    job = await create_metadata_sync_job_request(db, trigger="manual", book_ids=[])
    assert job.scope == {"book_ids": []}
    get_targets.assert_awaited_once_with(db, [])
    get_library.assert_not_called()


@pytest.mark.parametrize(
    "details",
    [
        {"series_index": True},
        {"series_index": float("inf")},
        {"page_count": "120"},
        {"publisher": ["Publisher"]},
        {"corroborating_sources": "amazon"},
        {"custom": object()},
    ],
)
def test_invalid_known_metadata_fields_and_non_json_extensions_are_rejected(details):
    with pytest.raises(ValidationError):
        metadata_details(details)


@pytest.mark.parametrize("identifiers", [{"isbn_13": ["9781402894626"]}, {"asin": True}, {"custom": object()}])
def test_invalid_identifier_shapes_are_rejected(identifiers):
    with pytest.raises(ValidationError):
        remote_identifiers(identifiers)


def test_suggestion_preserves_json_extensions_and_known_nullable_legacy_fields():
    book = models.Book(
        id=1,
        title="Example",
        author="Author",
        genre_tags=[],
        metadata_remote_ids={"calibre_id": 17, "custom": {"labels": ["original", None]}},
        metadata_details={"custom": {"edition": 3}, "page_count": None},
    )
    suggestion = MetadataSuggestion(
        book=book,
        matched=True,
        remote_ids={"isbn_13": "9781402894626", "catalog": {"id": 9}},
        metadata_details={"publisher": "Press", "published_date": 1998, "plugin": [1, False, None]},
    )
    assert apply_suggestion_to_book(book, suggestion)
    assert book.metadata_remote_ids == {
        "calibre_id": 17,
        "custom": {"labels": ["original", None]},
        "isbn_13": "9781402894626",
        "catalog": {"id": 9},
    }
    assert book.metadata_details == {
        "custom": {"edition": 3},
        "page_count": None,
        "publisher": "Press",
        "published_date": 1998,
        "plugin": [1, False, None],
    }
    assert suggestion.to_schema().metadata_details["plugin"] == [1, False, None]


def test_mutated_suggestion_is_revalidated_before_applying_any_fields():
    book = models.Book(id=1, title="Example", author="Author", genre_tags=["Fantasy"], metadata_details={"publisher": "Old"})
    suggestion = MetadataSuggestion(book=book, matched=True, genre_tags=["Mystery"], metadata_details={"publisher": "New"})
    suggestion.metadata_details["series_index"] = True
    before = deepcopy(book.metadata_details)
    with pytest.raises(ValidationError):
        apply_suggestion_to_book(book, suggestion)
    assert book.metadata_details == before
    assert book.genre_tags == ["Fantasy"]
    assert book.metadata_synced_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ids,details", [({"isbn_13": ["9781402894626"]}, {"publisher": "New"}), ({}, {"series_index": "two"})]
)
async def test_malformed_persisted_match_does_not_mutate_book_or_approval_history(db, ids, details):
    book = await crud.create_book(
        db,
        schemas.BookCreate(title="Example", author="Author", source_type=models.SourceType.epub, genre_tags=["Fantasy"]),
    )
    match = models.BookMetadataMatch(
        book_id=book.id,
        status="pending",
        remote_ids=ids,
        remote_metadata=details,
        proposed_genre_tags=["Mystery"],
    )
    db.add(match)
    await db.flush()
    proposal = models.MetadataProposal(book_id=book.id, match_id=match.id, status="open")
    db.add(proposal)
    await db.commit()
    before_revisions = await db.scalar(select(func.count()).select_from(models.BookRevision))

    with pytest.raises(ValidationError):
        await approve_metadata_match(db, match.id)

    assert book.genre_tags == ["Fantasy"]
    assert book.metadata_details is None
    assert match.status == "pending"
    assert match.approved_at is None
    assert proposal.status == "open"
    assert await db.scalar(select(func.count()).select_from(models.BookRevision)) == before_revisions


def test_nested_legacy_identifiers_do_not_create_exact_identifier_matches():
    kwargs = dict(
        local_title="One story", local_author="One author", remote_title="Different story", remote_authors=["Other author"]
    )
    expected = score_metadata_candidate(**kwargs)
    assert (
        score_metadata_candidate(**kwargs, local_ids={"isbn_13": ["9781402894626"]}, remote_ids={"isbn_13": "9781402894626"})
        == expected
    )
    assert score_metadata_candidate(**kwargs, local_ids={"asin": {"id": 1}}, remote_ids={"asin": {"id": 1}}) == expected


def test_malformed_series_positions_do_not_become_bool_or_infinite_series_numbers():
    assert (
        series_match_issues(local_title="Example", remote_title="Example", local_series_index=True, remote_series_index=2)
        == []
    )
    assert (
        series_match_issues(
            local_title="Example", remote_title="Example", local_series_index=float("inf"), remote_series_index=2
        )
        == []
    )
