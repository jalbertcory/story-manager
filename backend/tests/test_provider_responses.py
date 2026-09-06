"""Regression tests for untrusted model output and metadata provider records."""

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.app import crud, models
from backend.app.services import audiobook_llm, metadata_sync
from backend.app.services.llm_responses import AnthropicResponse, ChatResponse, OllamaResponse, RosterResponse
from backend.app.services.metadata import arbitration, evidence
from backend.app.services.metadata.responses import GOOGLE_VOLUME, OPEN_LIBRARY_DOC, valid_records


def llm_settings():
    return models.AudiobookSettings(llm_provider="ollama", llm_base_url="http://llm.test")


def search_identity():
    return evidence.SearchIdentity(
        title="Book",
        author="Author",
        series=None,
        series_index=None,
        remote_ids={},
        opening_excerpt="Book by Author",
    )


@pytest.mark.parametrize(
    "change",
    [
        {"exact_match": "false"},
        {"selected_index": True},
        {"selected_index": "0"},
        {"selected_index": 99},
        {"selected_index": -2},
        {"confidence": "high"},
        {"confidence": float("nan")},
        {"confidence": float("inf")},
        {"confidence": 1.1},
        {"confidence": True},
        {"reason": ["looks right"]},
    ],
)
@pytest.mark.asyncio
async def test_invalid_arbitration_keeps_ranking_and_scores(monkeypatch, change):
    book = models.Book(id=1, title="Book", author="Author")
    candidates = [
        metadata_sync.MetadataSuggestion(book=book, matched=True, match_confidence=0.85),
        metadata_sync.MetadataSuggestion(book=book, matched=True, match_confidence=0.84),
    ]
    payload = {"selected_index": 1, "exact_match": True, "confidence": 0.98, "reason": "Exact", **change}
    monkeypatch.setattr(arbitration, "_call_llm", AsyncMock(return_value=json.dumps(payload)))
    result = await arbitration.arbitrate_candidate_suggestions(book, search_identity(), candidates, llm_settings())
    assert result is candidates
    assert [c.match_confidence for c in result] == [0.85, 0.84]
    assert all(c.note is None and c.match_issues is None for c in result)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"title": {}, "author": "A", "confidence": 0.99, "reason": "x"},
        {"title": "New", "author": "A", "confidence": "0.99", "reason": "x"},
    ],
)
@pytest.mark.asyncio
async def test_bad_search_refinement_is_noncritical(monkeypatch, payload):
    monkeypatch.setattr(arbitration, "_call_llm", AsyncMock(return_value=json.dumps(payload)))
    assert await arbitration.refine_unmatched_search_identity(search_identity(), llm_settings()) is None


@pytest.mark.asyncio
async def test_invalid_inferred_identity_preserves_deterministic_evidence(monkeypatch):
    book = models.Book(id=1, title="Pending", author="Pending")
    epub = evidence.EpubEvidence(package_title="Real title", package_author="Real author")
    monkeypatch.setattr(evidence, "extract_epub_evidence", lambda _: epub)
    monkeypatch.setattr(
        evidence,
        "_call_llm",
        AsyncMock(
            return_value=json.dumps(
                {
                    "title": "Wrong title",
                    "author": "Wrong author",
                    "confidence": float("nan"),
                    "reason": "x",
                }
            )
        ),
    )
    result = await evidence.resolve_search_identity(book, llm_settings())
    assert (result.title, result.author, result.used_llm) == ("Real title", "Real author", False)


@pytest.mark.parametrize(
    "change",
    [
        {"i": True},
        {"c": True},
        {"c": "7"},
        {"c": []},
        {"e": {}},
        {"confidence": float("nan")},
        {"confidence": 2},
        {"reason": []},
    ],
)
def test_bad_diarization_rows_are_retried_while_valid_rows_survive(change):
    raw = json.dumps({"assignments": [{"i": 1, "c": 7, **change}, {"i": 2, "c": 7}]})
    result, missing, salvaged = audiobook_llm._parse_diarization_response(raw, [1, 2])
    assert [row["id"] for row in result["assignments"]] == [2]
    assert missing == {1}
    assert not salvaged


def test_truncated_diarization_cannot_inject_internal_fallback_flag():
    raw = '{"assignments":[{"i":1,"c":7,"_fallback":true},{"i":2,"c":'
    result, missing, salvaged = audiobook_llm._parse_diarization_response(raw, [1, 2])
    assert "_fallback" not in result["assignments"][0]
    assert missing == {2}
    assert salvaged


@pytest.mark.parametrize(
    "character",
    [
        {"name": {}},
        {"name": "Narrator", "aliases": "Alias"},
        {"name": "Narrator", "evidence": [12]},
        {"name": "Narrator", "is_narrator": "false"},
    ],
)
@pytest.mark.asyncio
async def test_invalid_roster_does_not_replace_existing_characters(db, monkeypatch, character):
    book = models.Book(
        title="Book",
        author="Author",
        source_type=models.SourceType.epub,
        immutable_path="book.epub",
        current_path="book.epub",
        audiobook_enabled=True,
    )
    db.add(book)
    db.add(llm_settings())
    await db.commit()
    await crud.audiobook.create_chapter(db, book.id, 1, "chapter.xhtml")
    old = await crud.audiobook.create_characters_bulk(db, book.id, [{"name": "Existing", "is_narrator": True}])
    monkeypatch.setattr(
        audiobook_llm,
        "_call_llm",
        AsyncMock(
            return_value=json.dumps(
                {
                    "book_summary": "Changed",
                    "characters": [{"name": "Valid"}, character],
                }
            )
        ),
    )
    with pytest.raises(RuntimeError, match="invalid character roster"):
        await audiobook_llm.generate_character_roster(book.id, db)
    remaining = await crud.audiobook.get_characters_for_book(db, book.id)
    assert [c.id for c in remaining] == [old[0].id]
    assert book.audiobook_summary is None


def test_roster_legacy_optional_fields_and_fenced_json():
    roster = RosterResponse.model_validate(audiobook_llm._extract_json('```json\n{"characters":[{"name":"Narrator"}]}\n```'))
    assert roster.characters[0].aliases == []
    assert roster.book_summary is None


@pytest.mark.parametrize(
    "model,payload",
    [
        (ChatResponse, {"choices": []}),
        (ChatResponse, {"choices": [{"message": {"content": False}}]}),
        (OllamaResponse, {"message": {"content": ["text"]}}),
        (AnthropicResponse, {"content": [{"text": {}}]}),
    ],
)
def test_transport_envelopes_require_text(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_anthropic_ignores_non_text_blocks_and_keeps_all_text():
    response = AnthropicResponse.model_validate(
        {
            "content": [
                {"type": "thinking", "thinking": "internal"},
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ]
        }
    )
    assert response.text_content() == "firstsecond"


@pytest.mark.parametrize("envelope", [[], {"items": {}}, {"items": "bad"}])
def test_invalid_metadata_envelopes_are_empty(envelope):
    assert valid_records(envelope, "items", GOOGLE_VOLUME) == []


def test_open_library_skips_bad_records_and_accepts_sparse_legacy_shapes(monkeypatch):
    monkeypatch.setattr(
        metadata_sync,
        "_request_json",
        lambda *a, **kw: {
            "docs": [
                {"title": "Good", "author_name": "Author", "isbn": "9780123456786", "newField": {}},
                {"title": {"bad": "title"}},
                {"title": "Bad authors", "author_name": [False]},
                {"title": "Bad cover", "cover_i": True},
            ]
        },
    )
    docs = metadata_sync._fetch_search_docs({"title": "Good"})
    assert docs == [{"title": "Good", "author_name": "Author", "isbn": "9780123456786"}]
    assert metadata_sync._score_search_doc(models.Book(title="Good", author="Author"), docs[0]) > 0.7


def test_google_volume_validation_reaches_scoring_with_nested_metadata(monkeypatch):
    good = {
        "id": "good",
        "volumeInfo": {
            "title": "Good",
            "authors": ["Author"],
            "categories": "Fiction",
            "pageCount": 100,
            "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780123456786"}],
            "seriesInfo": {"shortSeriesBookTitle": "Series", "volumeSeries": [{"orderNumber": {"number": "2"}}]},
        },
    }
    monkeypatch.setattr(metadata_sync, "_google_books_enabled", lambda: True)
    monkeypatch.setattr(
        metadata_sync,
        "_request_google_books_json",
        lambda *a, **kw: {
            "items": [
                good,
                {"id": "bad", "volumeInfo": {"industryIdentifiers": "ISBN"}},
                {"id": "bad", "volumeInfo": {"pageCount": True}},
                {"id": "bad", "volumeInfo": {"seriesInfo": {"volumeSeries": ["bad"]}}},
            ]
        },
    )
    volumes = metadata_sync._fetch_google_books_volumes("Good")
    assert volumes == [good]
    assert metadata_sync._google_books_metadata_details(volumes[0])["series_index"] == 2
    assert metadata_sync._extract_google_remote_ids(volumes[0])["isbn_13"] == "9780123456786"


def test_invalid_single_volume_and_work_are_noncritical(monkeypatch):
    monkeypatch.setattr(metadata_sync, "_google_books_enabled", lambda: True)
    monkeypatch.setattr(metadata_sync, "_request_google_books_json", lambda *a, **kw: {"volumeInfo": []})
    monkeypatch.setattr(metadata_sync, "_request_json", lambda *a, **kw: {"description": {"value": 17}})
    assert metadata_sync._fetch_google_books_volume_by_id("bad") is None
    assert metadata_sync._fetch_work_data({"key": "/works/bad"}) == {}


def test_author_work_entries_skip_bad_titles_without_losing_valid_works(monkeypatch):
    monkeypatch.setattr(
        metadata_sync,
        "_request_json",
        lambda *a, **kw: {
            "entries": [
                {"key": "/works/good", "title": " Good "},
                {"title": ["Bad"]},
                {"title": None},
            ]
        },
    )
    cache = {}
    assert metadata_sync._fetch_author_work_entries("author", cache) == [{"key": "/works/good", "title": "Good"}]
    assert cache["author"][0]["title"] == "Good"


def test_provider_models_reject_boolean_numeric_fields():
    assert valid_records({"docs": [{"title": "Bad", "series_index": True}]}, "docs", OPEN_LIBRARY_DOC) == []


def test_unscored_duplicate_does_not_replace_explicit_confidence():
    raw = json.dumps(
        {
            "assignments": [
                {"i": 1, "c": 7, "confidence": 0.8},
                {"i": 1, "c": 8},
            ]
        }
    )
    result, missing, _ = audiobook_llm._parse_diarization_response(raw, [1])
    assert result["assignments"][0]["character_id"] == 7
    assert not missing


def test_malformed_manual_work_is_not_replaced_with_local_identity(monkeypatch):
    monkeypatch.setattr(metadata_sync, "_fetch_search_docs", lambda _: [])
    monkeypatch.setattr(metadata_sync, "_request_json", lambda *a, **kw: {"title": ["Invalid"]})
    book = models.Book(id=1, title="Book", author="Author", metadata_remote_ids={"open_library_work_key": "/works/bad"})
    assert metadata_sync._collect_search_doc_candidates(book, local_books_by_author={}, author_work_cache={}) == []
