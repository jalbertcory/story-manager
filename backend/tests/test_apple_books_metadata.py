import pytest
import requests

from backend.app import models
from backend.app.services.metadata.clients import request_apple_books_json
from backend.app.services.metadata.providers.apple_books import (
    AppleBooksMatch,
    build_apple_books_suggestion,
    collect_apple_books_matches,
)
from backend.app.services.metadata_sync import _build_suggestions_for_book, _merge_sources

CLIENTS = "backend.app.services.metadata.clients"
PROVIDER = "backend.app.services.metadata.providers.apple_books"

HIDDEN_CROWN = {
    "trackId": 1234567890,
    "trackName": "The Hidden Crown",
    "artistName": "Élodie Martin",
    "genres": ["Epic Fantasy", "Books", "Sci-Fi & Fantasy"],
    "description": "<p>A <b>crown</b> lost.</p>",
    "releaseDate": "2021-03-04T08:00:00Z",
    "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/Publication/v4/ab/cd/cover.jpg/100x100bb.jpg",
    "trackViewUrl": "https://books.apple.com/us/book/the-hidden-crown/id1234567890",
    "kind": "ebook",
    "averageUserRating": 4.5,
}


@pytest.fixture
def apple_enabled(mocker):
    mocker.patch(f"{CLIENTS}.APPLE_BOOKS_METADATA_ENABLED", True)


def _response(mocker, payload, status_code=200):
    response = mocker.Mock(status_code=status_code, headers={})
    response.json.return_value = payload
    return response


def test_apple_books_is_not_queried_when_disabled(mocker):
    request = mocker.patch(f"{CLIENTS}.requests.get")

    assert request_apple_books_json("/search", params={"term": "Dune"}) == {}
    assert collect_apple_books_matches(models.Book(id=1, title="Dune", author="Frank Herbert")) == []
    request.assert_not_called()


def test_apple_books_search_builds_a_scored_suggestion(mocker, apple_enabled):
    unrelated = {**HIDDEN_CROWN, "trackId": 99, "trackName": "Cooking for Kings", "artistName": "Someone Else"}
    malformed = {"trackId": "not-a-number", "trackName": "The Hidden Crown"}
    request = mocker.patch(
        f"{CLIENTS}.requests.get",
        return_value=_response(mocker, {"resultCount": 3, "results": [unrelated, malformed, HIDDEN_CROWN]}),
    )
    book = models.Book(id=11, title="The Hidden Crown", author="Élodie Martin", genre_tags=[])

    matches = collect_apple_books_matches(book)

    assert [match.apple_books_id for match in matches] == ["1234567890"]
    params = request.call_args.kwargs["params"]
    assert params["term"] == "The Hidden Crown Élodie Martin"
    assert (params["media"], params["entity"], params["country"]) == ("ebook", "ebook", "us")
    match = matches[0]
    assert match.categories == ["Epic Fantasy", "Sci-Fi & Fantasy"]
    assert match.metadata_details["description"] == "A crown lost."
    assert match.metadata_details["published_date"] == "2021-03-04"
    assert match.metadata_details["cover_url"].endswith("/cover.jpg/1200x1200bb.jpg")

    suggestion = build_apple_books_suggestion(book, match)
    assert suggestion.source == "apple_books"
    assert suggestion.remote_ids == {"apple_books_id": "1234567890"}
    assert suggestion.remote_url == HIDDEN_CROWN["trackViewUrl"]
    assert suggestion.remote_author == "Élodie Martin"


def test_pinned_apple_books_id_is_looked_up_directly(mocker, apple_enabled):
    request = mocker.patch(f"{CLIENTS}.requests.get", return_value=_response(mocker, {"results": [HIDDEN_CROWN]}))
    book = models.Book(
        id=12,
        title="Hidden Crown (Omnibus Rip)",
        author="E. Martin",
        metadata_remote_ids={"apple_books_id": "1234567890"},
    )

    matches = collect_apple_books_matches(book)

    assert request.call_count == 1
    assert request.call_args.args[0].endswith("/lookup")
    assert request.call_args.kwargs["params"]["id"] == "1234567890"
    assert matches and matches[0].match_confidence >= 0.97


def test_apple_books_client_retries_rate_limit_and_survives_failures(mocker, apple_enabled):
    limited = _response(mocker, {}, status_code=429)
    request = mocker.patch(f"{CLIENTS}.requests.get", side_effect=[limited, _response(mocker, {"results": [HIDDEN_CROWN]})])
    mocker.patch(f"{CLIENTS}.time.sleep")

    assert request_apple_books_json("/search", params={"term": "x"})["results"] == [HIDDEN_CROWN]
    assert request.call_count == 2

    mocker.patch(f"{CLIENTS}.requests.get", side_effect=requests.ConnectionError("offline"))
    assert collect_apple_books_matches(models.Book(id=1, title="The Hidden Crown", author="Élodie Martin")) == []


def _apple_match() -> AppleBooksMatch:
    return AppleBooksMatch(
        apple_books_id="1234567890",
        title="The Hidden Crown",
        authors=["Élodie Martin"],
        categories=["Epic Fantasy"],
        remote_url="https://books.apple.com/us/book/id1234567890",
        remote_ids={"apple_books_id": "1234567890"},
        metadata_details={"cover_url": "https://example.test/cover.jpg"},
        match_confidence=0.95,
    )


def _patch_other_providers(mocker, *, google):
    mocker.patch("backend.app.services.metadata_sync._collect_search_doc_candidates", return_value=[])
    mocker.patch("backend.app.services.metadata_sync._collect_google_books_matches", return_value=google)
    mocker.patch("backend.app.services.metadata_sync._collect_amazon_matches", return_value=[])
    return mocker.patch("backend.app.services.metadata_sync._collect_apple_books_matches", return_value=[_apple_match()])


def test_apple_books_fills_in_when_other_providers_miss(mocker):
    book = models.Book(id=11, title="The Hidden Crown", author="Élodie Martin")
    apple = _patch_other_providers(mocker, google=[])

    suggestions = _build_suggestions_for_book(book, {}, {}, max_candidates=5)

    apple.assert_called_once()
    assert [suggestion.source for suggestion in suggestions] == ["apple_books"]
    assert suggestions[0].remote_ids == {"apple_books_id": "1234567890"}


def test_apple_books_is_skipped_when_another_provider_matched(mocker):
    from backend.app.services.metadata.providers.google_books import GoogleBooksMatch

    google = GoogleBooksMatch(
        volume_id="g1",
        title="The Hidden Crown",
        authors=["Élodie Martin"],
        categories=["Fantasy"],
        info_link=None,
        remote_ids={"google_books_volume_id": "g1"},
        metadata_details={},
        match_confidence=1.0,
    )
    book = models.Book(id=11, title="The Hidden Crown", author="Élodie Martin")
    apple = _patch_other_providers(mocker, google=[google])

    suggestions = _build_suggestions_for_book(book, {}, {}, max_candidates=5)
    assert [suggestion.source for suggestion in suggestions] == ["google_books"]
    apple.assert_not_called()

    pinned = models.Book(
        id=12, title="The Hidden Crown", author="Élodie Martin", metadata_remote_ids={"apple_books_id": "1234567890"}
    )
    suggestions = _build_suggestions_for_book(pinned, {}, {}, max_candidates=5)
    apple.assert_called_once()
    assert suggestions[0].source == "google_books+apple_books"


def test_merge_sources_keeps_apple_books():
    assert _merge_sources("apple_books", "open_library+amazon") == "open_library+amazon+apple_books"
