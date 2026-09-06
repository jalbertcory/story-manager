import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from ebooklib import epub

from backend.app import crud, models, schemas
from backend.app.services.metadata.amazon import enrich_amazon_candidate, search_amazon
from backend.app.services.metadata.arbitration import arbitrate_candidate_suggestions, refine_unmatched_search_identity
from backend.app.services.metadata.clients import request_google_books_json
from backend.app.services.metadata.evidence import EpubEvidence, extract_epub_evidence, resolve_search_identity
from backend.app.services.metadata.scoring import (
    author_similarity,
    bibliographic_title_variants,
    infer_series_metadata,
    score_metadata_candidate,
    series_match_issues,
    title_similarity,
)
from backend.app.services.metadata_jobs import _sync_one_book, approve_metadata_match
from backend.app.services.metadata_sync import MetadataSuggestion
from backend.app.services.metadata_sync import (
    GoogleBooksMatch,
    _annotate_duplicate_assignments,
    _build_suggestions_for_book,
    _google_books_metadata_details,
    allocate_unique_candidate_suggestions,
)
from backend.app.services.series import enrich_series_metadata


def _write_evidence_epub(path):
    book = epub.EpubBook()
    book.set_identifier("urn:isbn:978-1-4028-9462-6")
    book.set_title("Untitled")
    book.add_author("Unknown")
    page = epub.EpubHtml(title="Title Page", file_name="title.xhtml", lang="en")
    page.content = """
    <html><body>
      <h1>The Hidden Crown</h1>
      <p>By Élodie Martin</p>
      <p>Starbound Series — Book 2</p>
      <p>ISBN 978-1-4028-9462-6</p>
    </body></html>
    """
    book.add_item(page)
    book.toc = (page,)
    book.spine = ["nav", page]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)


def test_epub_evidence_reads_title_page_byline_and_isbn(tmp_path, mocker):
    path = tmp_path / "evidence.epub"
    _write_evidence_epub(path)
    local_book = models.Book(id=7, title="Pending", author="Pending", current_path="unused.epub")
    mocker.patch("backend.app.services.metadata.evidence._book_path", return_value=path)

    evidence = extract_epub_evidence(local_book)

    assert evidence.heading_title == "The Hidden Crown"
    assert evidence.byline_author == "Élodie Martin"
    assert evidence.content_series == "Starbound"
    assert evidence.content_series_index == 2
    assert evidence.remote_ids["isbn_13"] == "9781402894626"
    assert "The Hidden Crown" in evidence.opening_content


@pytest.mark.asyncio
async def test_search_identity_uses_opening_content_when_package_metadata_is_generic(tmp_path, mocker):
    path = tmp_path / "identity.epub"
    _write_evidence_epub(path)
    local_book = models.Book(id=8, title="Pending", author="Pending", current_path="unused.epub")
    mocker.patch("backend.app.services.metadata.evidence._book_path", return_value=path)

    identity = await resolve_search_identity(local_book, None)

    assert identity.title == "The Hidden Crown"
    assert identity.author == "Élodie Martin"
    assert identity.series == "Starbound"
    assert identity.series_index == 2
    assert identity.remote_ids["isbn_13"] == "9781402894626"
    assert identity.evidence_note == "title from EPUB; author from EPUB; series from EPUB"


@pytest.mark.asyncio
async def test_search_identity_uses_llm_to_resolve_conflicting_epub_evidence(mocker):
    local_book = models.Book(id=9, title="Filename Export 19", author="Unknown", current_path="unused.epub")
    evidence = EpubEvidence(
        package_title="Archive Export",
        package_author="Uploader",
        heading_title="A Memory of Stars",
        byline_author="N. K. Vale",
        opening_content="A Memory of Stars\nBy N. K. Vale\nCopyright 2024\nISBN 9780123456786",
    )
    settings = models.AudiobookSettings(
        llm_provider="openai",
        llm_base_url="http://llm.test",
        llm_model="test-model",
        llm_endpoints=[{"id": "metadata-test", "provider": "openai", "base_url": "http://llm.test"}],
    )
    mocker.patch("backend.app.services.metadata.evidence.extract_epub_evidence", return_value=evidence)
    llm = mocker.patch(
        "backend.app.services.metadata.evidence._call_llm",
        new=mocker.AsyncMock(
            return_value=json.dumps(
                {
                    "title": "A Memory of Stars",
                    "author": "N. K. Vale",
                    "series": "Starbound",
                    "series_index": 2,
                    "isbn_10": "",
                    "isbn_13": "9780123456786",
                    "confidence": 0.96,
                    "reason": "Explicit title, byline, and copyright-page ISBN.",
                }
            )
        ),
    )

    identity = await resolve_search_identity(local_book, settings)

    assert identity.title == "A Memory of Stars"
    assert identity.author == "N. K. Vale"
    assert identity.series == "Starbound"
    assert identity.series_index == 2
    assert identity.remote_ids["isbn_13"] == "9780123456786"
    assert identity.used_llm is True
    assert "LLM-confirmed EPUB identity" in identity.evidence_note
    llm.assert_awaited_once()


def test_match_scoring_normalizes_names_but_rejects_different_volume_numbers():
    assert author_similarity("Martin, Élodie", "Élodie Martin") == 1.0
    assert title_similarity("Dragon Road: Book 7", "Dragon Road Book 8") <= 0.68
    assert (
        score_metadata_candidate(
            local_title="Dragon Road: Book 7",
            local_author="Martin, Élodie",
            remote_title="Dragon Road Book 7",
            remote_authors=["Élodie Martin"],
        )
        > 0.95
    )
    assert (
        score_metadata_candidate(
            local_title="The Hidden Crown",
            local_author="Élodie Martin",
            remote_title="The Hidden Crown Summary and Study Guide",
            remote_authors=["Élodie Martin"],
        )
        <= 0.72
    )
    assert (
        score_metadata_candidate(
            local_title="The Hidden Crown",
            local_author="Élodie Martin",
            remote_title="The Hidden Crown",
            remote_authors=["Élodie Martin"],
            local_ids={"isbn_10": "1402894627"},
            remote_ids={"isbn_13": "9781402894626"},
        )
        == 1.0
    )


def test_series_order_is_first_class_match_evidence_even_with_stale_isbn():
    assert infer_series_metadata("Dragon Road, Vol. 8") == ("Dragon Road", 8.0)
    assert series_match_issues(
        local_title="The Ember Crown",
        local_series="Dragon Road",
        local_series_index=7,
        remote_title="The Ember Crown",
        remote_series="Dragon Road",
        remote_series_index=8,
    ) == ["Series position conflict: local book is #7, candidate is #8."]
    assert (
        score_metadata_candidate(
            local_title="The Ember Crown",
            local_author="Élodie Martin",
            remote_title="The Ember Crown",
            remote_authors=["Élodie Martin"],
            local_ids={"isbn_13": "9781402894626"},
            remote_ids={"isbn_13": "9781402894626"},
            local_series="Dragon Road",
            local_series_index=7,
            remote_series="Dragon Road",
            remote_series_index=8,
        )
        == 0.89
    )


def test_catalog_style_titles_reduce_to_provider_titles_and_series_positions():
    assert infer_series_metadata("Discworld 01: The Colour Of Magic", "Discworld") == ("Discworld", 1.0)
    assert infer_series_metadata("The Silver Crown: Book Three of The Guardians", "The Guardians") == (
        "The Guardians",
        3.0,
    )
    assert "The Colour Of Magic" in bibliographic_title_variants(
        "Discworld 01: The Colour Of Magic",
        "Discworld",
    )
    assert "Past Tense" in bibliographic_title_variants(
        "Past Tense (Schooled in Magic Book 10)",
        "Schooled in Magic",
    )
    assert (
        score_metadata_candidate(
            local_title="Discworld 01: The Colour Of Magic",
            local_author="Terry Pratchett",
            local_series="Discworld",
            remote_title="The Colour of Magic",
            remote_authors=["Terry Pratchett"],
        )
        > 0.95
    )


def test_series_enrichment_fills_positions_without_overwriting_existing_values():
    books = [
        models.Book(title="Discworld 01: The Colour Of Magic", author="Terry Pratchett", series="Discworld"),
        models.Book(
            title="Past Tense (Schooled in Magic Book 10)",
            author="Christopher Nuttall",
            series="Schooled in Magic",
        ),
        models.Book(title="Manual", author="Author", series="Saga", series_index=4),
    ]

    changed = enrich_series_metadata(books)

    assert [float(book.series_index) for book in books] == [1.0, 10.0, 4.0]
    assert changed == books[:2]


@pytest.mark.asyncio
async def test_llm_arbitration_promotes_opening_page_verified_candidate(mocker):
    book = models.Book(id=91, title="The Ember Crown", author="Élodie Martin")
    candidates = [
        MetadataSuggestion(
            book=book,
            matched=True,
            source="open_library",
            match_confidence=0.86,
            remote_title="The Ember Crown Workbook",
            remote_author="Élodie Martin",
            remote_ids={"open_library_work_key": "/works/workbook"},
        ),
        MetadataSuggestion(
            book=book,
            matched=True,
            source="google_books",
            match_confidence=0.84,
            remote_title="The Ember Crown",
            remote_author="Élodie Martin",
            remote_ids={"google_books_volume_id": "exact"},
        ),
    ]
    settings = models.AudiobookSettings(
        llm_provider="openai",
        llm_base_url="http://llm.test",
        llm_model="test-model",
        llm_endpoints=[{"id": "metadata", "provider": "openai", "base_url": "http://llm.test"}],
    )
    mocker.patch(
        "backend.app.services.metadata.arbitration._call_llm",
        new=mocker.AsyncMock(
            return_value=json.dumps(
                {
                    "selected_index": 1,
                    "exact_match": True,
                    "confidence": 0.95,
                    "reason": "The title page exactly names the second candidate.",
                }
            )
        ),
    )
    identity = SimpleNamespace(
        title=book.title,
        author=book.author,
        series=None,
        series_index=None,
        remote_ids={},
        opening_excerpt="The Ember Crown\nBy Élodie Martin\nCopyright 2024",
    )

    ranked = await arbitrate_candidate_suggestions(book, identity, candidates, settings)

    assert ranked[0].remote_ids == {"google_books_volume_id": "exact"}
    assert ranked[0].match_confidence == 0.99
    assert "title page exactly names" in ranked[0].note


@pytest.mark.asyncio
async def test_llm_creates_one_high_confidence_retry_query_for_unmatched_epub(mocker):
    settings = models.AudiobookSettings(
        llm_provider="ollama",
        llm_base_url="http://llm.test",
        llm_model="test-model",
        llm_endpoints=[{"id": "metadata", "provider": "ollama", "base_url": "http://llm.test"}],
    )
    mocker.patch(
        "backend.app.services.metadata.arbitration._call_llm",
        new=mocker.AsyncMock(
            return_value=json.dumps(
                {
                    "title": "The Colour of Magic",
                    "author": "Terry Pratchett",
                    "confidence": 0.98,
                    "reason": "Explicit title and author on the title page.",
                }
            )
        ),
    )
    identity = SimpleNamespace(
        title="Discworld 01 The Colour Of Magic retail",
        author="Unknown Exporter",
        opening_excerpt="The Colour of Magic\nTerry Pratchett\nCopyright 1983",
        used_llm=False,
    )

    refined = await refine_unmatched_search_identity(identity, settings)

    assert refined is not None
    assert refined.model_dump(exclude={"confidence"}) == {
        "title": "The Colour of Magic",
        "author": "Terry Pratchett",
        "reason": "Explicit title and author on the title page.",
    }


def test_google_books_structured_series_metadata_is_retained():
    details = _google_books_metadata_details(
        {
            "volumeInfo": {
                "title": "The Ember Crown",
                "seriesInfo": {
                    "shortSeriesBookTitle": "Dragon Road",
                    "volumeSeries": [{"orderNumber": 8}],
                    "bookDisplayNumber": "8",
                },
            }
        }
    )

    assert details["series"] == "Dragon Road"
    assert details["series_index"] == 8.0


def test_duplicate_remote_assignment_is_flagged_for_review():
    current = models.Book(id=12, title="Dragon Road 8", author="Élodie Martin")
    peer = models.Book(
        id=11,
        title="Dragon Road 7",
        author="Élodie Martin",
        metadata_remote_ids={"google_books_volume_id": "same-volume"},
    )
    suggestion = MetadataSuggestion(
        book=current,
        matched=True,
        match_confidence=0.99,
        remote_title="Dragon Road 8",
        remote_ids={"google_books_volume_id": "same-volume"},
    )

    _annotate_duplicate_assignments(current, [suggestion], [peer, current])

    assert suggestion.match_confidence == 0.89
    assert suggestion.match_issues == [
        'Remote record is already assigned to "Dragon Road 7" (local book #11); ' "verify this is not the wrong series volume."
    ]


def test_collection_wide_allocator_gives_shared_record_to_best_fitting_volume():
    book_one = models.Book(id=21, title="Dragon Road 1", author="Élodie Martin")
    book_two = models.Book(id=22, title="Dragon Road 2", author="Élodie Martin")
    record_one_for_one = MetadataSuggestion(
        book=book_one,
        matched=True,
        match_confidence=1.0,
        remote_title="Dragon Road 1",
        remote_ids={"open_library_work_key": "/works/one"},
    )
    record_one_for_two = MetadataSuggestion(
        book=book_two,
        matched=True,
        match_confidence=0.89,
        remote_title="Dragon Road 1",
        remote_ids={"open_library_work_key": "/works/one"},
    )
    record_two_for_two = MetadataSuggestion(
        book=book_two,
        matched=True,
        match_confidence=0.98,
        remote_title="Dragon Road 2",
        remote_ids={"open_library_work_key": "/works/two"},
    )

    allocated = allocate_unique_candidate_suggestions(
        [book_one, book_two],
        [[record_one_for_one], [record_one_for_two, record_two_for_two]],
    )

    assert allocated[0][0].remote_ids == {"open_library_work_key": "/works/one"}
    assert allocated[1][0].remote_ids == {"open_library_work_key": "/works/two"}
    assert record_one_for_two.match_issues == ['Collection-wide assignment reserved this remote record for "Dragon Road 1".']


def test_amazon_collector_parses_search_and_detail_metadata(mocker):
    search_html = """
    <div data-component-type="s-search-result" data-asin="B012345678">
      <h2><a href="/dp/B012345678"><span>The Hidden Crown</span></a></h2>
      <div class="a-row a-size-base a-color-secondary"><a>Élodie Martin</a></div>
    </div>
    """
    detail_html = """
    <span id="productTitle">The Hidden Crown</span>
    <div id="bylineInfo"><span class="author"><a>Élodie Martin</a></span></div>
    <div id="detailBullets_feature_div">
      ISBN-13: 978-1-4028-9462-6
      <span class="zg_hrsr"><a>Fantasy (Books)</a></span>
    </div>
    """
    request = mocker.patch(
        "backend.app.services.metadata.amazon.request_amazon_html",
        side_effect=[search_html, detail_html],
    )

    candidates = search_amazon("The Hidden Crown Élodie Martin")
    detailed = enrich_amazon_candidate(candidates[0])

    assert detailed.asin == "B012345678"
    assert detailed.authors == ["Élodie Martin"]
    assert detailed.isbn_13 == "9781402894626"
    assert detailed.categories == ["Fantasy"]
    assert request.call_count == 2


def test_google_books_client_retries_rate_limit_response(mocker):
    rate_limited = mocker.Mock(status_code=429, headers={"Retry-After": "0"})
    success = mocker.Mock(status_code=200, headers={})
    success.json.return_value = {"items": [{"id": "volume-1"}]}
    request = mocker.patch(
        "backend.app.services.metadata.clients.requests.get",
        side_effect=[rate_limited, success],
    )
    sleep = mocker.patch("backend.app.services.metadata.clients.time.sleep")
    mocker.patch("backend.app.services.metadata.clients.GOOGLE_BOOKS_API_KEY", "test-key")

    payload = request_google_books_json("/volumes", params={"q": "Dune"})

    assert payload["items"][0]["id"] == "volume-1"
    assert request.call_count == 2
    sleep.assert_called_once_with(0.25)


def test_provider_candidates_compete_in_one_ranked_pool(mocker):
    book = models.Book(id=11, title="The Hidden Crown", author="Élodie Martin")
    open_library_doc = {
        "key": "/works/study-guide",
        "title": "The Hidden Crown Summary and Study Guide",
        "author_name": ["Élodie Martin"],
        "author_key": ["OLAUTHOR"],
    }
    google_match = GoogleBooksMatch(
        volume_id="google-exact",
        title="The Hidden Crown",
        authors=["Élodie Martin"],
        categories=["Fantasy"],
        info_link="https://books.google.test/google-exact",
        remote_ids={"google_books_volume_id": "google-exact"},
        metadata_details={"publisher": "Crown Press"},
        match_confidence=1.0,
    )
    mocker.patch(
        "backend.app.services.metadata_sync._collect_search_doc_candidates",
        return_value=[(open_library_doc, 0.72)],
    )
    mocker.patch("backend.app.services.metadata_sync._collect_google_books_matches", return_value=[google_match])
    mocker.patch("backend.app.services.metadata_sync._collect_amazon_matches", return_value=[])
    mocker.patch("backend.app.services.metadata_sync._fetch_work_data", return_value={})
    mocker.patch("backend.app.services.metadata_sync._fetch_author_work_entries", return_value=[])

    suggestions = _build_suggestions_for_book(book, {"elodie martin": [book]}, {}, max_candidates=5)

    assert [suggestion.source for suggestion in suggestions] == ["google_books", "open_library"]
    assert suggestions[0].remote_ids == {"google_books_volume_id": "google-exact"}
    assert suggestions[0].metadata_details == {"publisher": "Crown Press"}


def test_two_independent_providers_create_near_perfect_corroborated_match(mocker):
    book = models.Book(id=14, title="The Hidden Crown", author="Élodie Martin")
    open_library_doc = {
        "key": "/works/exact",
        "title": "The Hidden Crown",
        "author_name": ["Élodie Martin"],
        "author_key": ["OLAUTHOR"],
        "isbn": ["9781402894626"],
    }
    google_match = GoogleBooksMatch(
        volume_id="google-exact",
        title="The Hidden Crown",
        authors=["Élodie Martin"],
        categories=[],
        info_link="https://books.google.test/google-exact",
        remote_ids={"google_books_volume_id": "google-exact", "isbn_13": "9781402894626"},
        metadata_details={},
        match_confidence=0.88,
    )
    mocker.patch(
        "backend.app.services.metadata_sync._collect_search_doc_candidates",
        return_value=[(open_library_doc, 0.88)],
    )
    mocker.patch("backend.app.services.metadata_sync._collect_google_books_matches", return_value=[google_match])
    mocker.patch("backend.app.services.metadata_sync._collect_amazon_matches", return_value=[])
    mocker.patch("backend.app.services.metadata_sync._fetch_work_data", return_value={})
    mocker.patch("backend.app.services.metadata_sync._fetch_author_work_entries", return_value=[])

    suggestions = _build_suggestions_for_book(book, {"elodie martin": [book]}, {}, max_candidates=5)

    assert len(suggestions) == 1
    assert suggestions[0].source == "open_library+google_books"
    assert suggestions[0].match_confidence == 0.98
    assert suggestions[0].metadata_details["corroborating_sources"] == ["open_library", "google_books"]


@pytest.mark.asyncio
async def test_approving_alternate_candidate_uses_its_own_metadata(db):
    book = await crud.create_book(
        db,
        schemas.BookCreate(
            title="Candidate Book",
            author="Candidate Author",
            immutable_path="candidate-immutable.epub",
            current_path="candidate.epub",
            source_type=models.SourceType.epub,
        ),
    )
    first = models.BookMetadataMatch(
        book_id=book.id,
        status="approved",
        source="open_library",
        remote_title="Candidate Book",
        remote_ids={"open_library_work_key": "/works/OL1W"},
        proposed_genre_tags=["Fantasy"],
        possible_missing_series_books=["Wrong Sequel"],
    )
    selected = models.BookMetadataMatch(
        book_id=book.id,
        status="pending",
        source="google_books",
        remote_title="Candidate Book",
        remote_ids={"google_books_volume_id": "g-1"},
        proposed_genre_tags=["Mystery"],
        possible_missing_series_books=[],
        note="Google Books has the exact ISBN.",
        remote_metadata={"publisher": "Selected Press", "language": "en"},
    )
    db.add_all([first, selected])
    book.metadata_remote_ids = {
        "open_library_work_key": "/works/OL1W",
        "isbn_13": "9780000000001",
        "calibre_id": "local-7",
    }
    await db.flush()
    db.add(
        models.MetadataProposal(
            book_id=book.id,
            match_id=first.id,
            status="open",
            proposed_genre_tags=["Fantasy"],
            possible_missing_series_books=["Wrong Sequel"],
        )
    )
    await db.commit()

    _match, proposal = await approve_metadata_match(db, selected.id)
    stored = await crud.get_book(db, book.id)

    assert stored.genre_tags == ["Mystery"]
    assert stored.metadata_remote_ids == {"calibre_id": "local-7", "google_books_volume_id": "g-1"}
    assert stored.metadata_sync_source == "google_books"
    assert stored.metadata_details == {"publisher": "Selected Press", "language": "en"}
    assert proposal.status == "resolved"
    assert proposal.note == "Google Books has the exact ISBN."
    assert first.status == "superseded"


@pytest.mark.asyncio
async def test_resync_reopens_approved_match_when_series_position_conflicts(db, mocker):
    book = await crud.create_book(
        db,
        schemas.BookCreate(
            title="The Ember Crown",
            author="Élodie Martin",
            series="Dragon Road",
            series_index=7,
            immutable_path="ember-immutable.epub",
            current_path="ember.epub",
            source_type=models.SourceType.epub,
        ),
    )
    approved = models.BookMetadataMatch(
        book_id=book.id,
        status="approved",
        source="google_books",
        match_confidence=0.99,
        remote_title="The Ember Crown",
        remote_ids={"google_books_volume_id": "wrong-volume"},
    )
    db.add(approved)
    await db.commit()
    suggestion = MetadataSuggestion(
        book=book,
        matched=True,
        source="google_books",
        match_confidence=0.89,
        remote_title="The Ember Crown",
        remote_ids={"google_books_volume_id": "wrong-volume"},
        metadata_details={"series": "Dragon Road", "series_index": 8},
        match_issues=["Series position conflict: local book is #7, candidate is #8."],
    )
    mocker.patch(
        "backend.app.services.metadata_jobs.generate_candidate_suggestions",
        new=mocker.AsyncMock(return_value=[[suggestion]]),
    )

    matched, proposed, applied = await _sync_one_book(
        db,
        book=book,
        all_books=[book],
        checked_at=datetime.now(timezone.utc),
    )
    await db.refresh(approved)
    proposal = await crud.get_metadata_proposal_by_book_id(db, book.id)

    assert (matched, proposed, applied) == (True, True, False)
    assert approved.status == "pending"
    assert approved.match_issues == ["Series position conflict: local book is #7, candidate is #8."]
    assert proposal.match_id == approved.id


@pytest.mark.asyncio
async def test_resync_auto_corrects_unambiguous_near_perfect_replacement(db, mocker):
    book = await crud.create_book(
        db,
        schemas.BookCreate(
            title="The Correct Crown",
            author="Élodie Martin",
            immutable_path="correct-immutable.epub",
            current_path="correct.epub",
            source_type=models.SourceType.epub,
        ),
    )
    book.metadata_remote_ids = {"open_library_work_key": "/works/wrong", "isbn_13": "9780000000001"}
    old_match = models.BookMetadataMatch(
        book_id=book.id,
        status="approved",
        source="open_library",
        match_confidence=0.93,
        remote_title="Wrong Crown",
        remote_ids={"open_library_work_key": "/works/wrong"},
    )
    db.add(old_match)
    await db.commit()
    replacement = MetadataSuggestion(
        book=book,
        matched=True,
        source="google_books",
        match_confidence=1.0,
        remote_title="The Correct Crown",
        remote_author="Élodie Martin",
        remote_ids={"google_books_volume_id": "correct", "isbn_13": "9780000000002"},
    )
    mocker.patch(
        "backend.app.services.metadata_jobs.generate_candidate_suggestions",
        new=mocker.AsyncMock(return_value=[[replacement]]),
    )

    matched, proposed, applied = await _sync_one_book(
        db,
        book=book,
        all_books=[book],
        checked_at=datetime.now(timezone.utc),
    )
    matches = await crud.get_metadata_matches_by_book_id(db, book.id)
    new_match = next(match for match in matches if (match.remote_ids or {}).get("google_books_volume_id"))

    assert (matched, proposed, applied) == (True, False, True)
    assert new_match.status == "auto_approved"
    assert old_match.status == "superseded"
    assert book.metadata_remote_ids == {"google_books_volume_id": "correct", "isbn_13": "9780000000002"}


@pytest.mark.asyncio
async def test_resync_skips_rejected_candidate_and_supersedes_stale_pending_match(db, mocker):
    book = await crud.create_book(
        db,
        schemas.BookCreate(
            title="Resync Book",
            author="Resync Author",
            immutable_path="resync-immutable.epub",
            current_path="resync.epub",
            source_type=models.SourceType.epub,
        ),
    )
    rejected = models.BookMetadataMatch(
        book_id=book.id,
        status="rejected",
        source="open_library",
        remote_ids={"open_library_work_key": "/works/rejected"},
    )
    stale = models.BookMetadataMatch(
        book_id=book.id,
        status="pending",
        source="open_library",
        remote_ids={"open_library_work_key": "/works/stale"},
    )
    db.add_all([rejected, stale])
    await db.flush()
    db.add(
        models.MetadataProposal(
            book_id=book.id,
            match_id=stale.id,
            status="open",
            proposed_genre_tags=["Old Genre"],
        )
    )
    await db.commit()

    suggestions = [
        MetadataSuggestion(
            book=book,
            matched=True,
            source="open_library",
            match_confidence=0.99,
            remote_title="Rejected Result",
            remote_ids={"open_library_work_key": "/works/rejected"},
        ),
        MetadataSuggestion(
            book=book,
            matched=True,
            source="google_books",
            match_confidence=0.88,
            remote_title="Resync Book",
            remote_author="Resync Author",
            remote_ids={"google_books_volume_id": "replacement"},
            new_genre_tags=["Mystery"],
        ),
    ]
    mocker.patch(
        "backend.app.services.metadata_jobs.generate_candidate_suggestions",
        new=mocker.AsyncMock(return_value=[suggestions]),
    )

    matched, proposed, applied = await _sync_one_book(
        db,
        book=book,
        all_books=[book],
        checked_at=datetime.now(timezone.utc),
    )
    matches = await crud.get_metadata_matches_by_book_id(db, book.id)
    replacement = next(match for match in matches if (match.remote_ids or {}).get("google_books_volume_id"))
    refreshed_stale = next(match for match in matches if match.id == stale.id)
    proposal = await crud.get_metadata_proposal_by_book_id(db, book.id)

    assert (matched, proposed, applied) == (True, True, False)
    assert replacement.status == "pending"
    assert replacement.proposed_genre_tags == ["Mystery"]
    assert refreshed_stale.status == "superseded"
    assert proposal.match_id == replacement.id


@pytest.mark.asyncio
async def test_review_queue_and_counts_exclude_dismiss_only_entries(db, app_client):
    from datetime import datetime, timezone

    pending_ids = []
    pending_matches = []
    for index, status in enumerate(
        ["pending", "auto_approved", "approved", "no_match", "rejected", "pending", None, "pending"]
    ):
        book = models.Book(title=f"Review {index}", author="Writer", source_type=models.SourceType.epub)
        if index == 7:
            book.deleted_at = datetime.now(timezone.utc)
        db.add(book)
        await db.flush()
        match = models.BookMetadataMatch(book_id=book.id, status=status) if status else None
        if match:
            db.add(match)
            await db.flush()
        db.add(
            models.MetadataProposal(
                book_id=book.id,
                match_id=match.id if match else None,
                status="open",
                possible_missing_series_books=["Informational only"],
            )
        )
        if status == "pending" and index != 7:
            pending_ids.append(book.id)
            pending_matches.append(match)
    await db.commit()

    # Filtering must happen before limit/offset, and the dashboard must agree.
    pages = [app_client.get(f"/api/metadata/inbox?limit=1&offset={offset}") for offset in range(3)]
    assert all(response.status_code == 200 for response in pages)
    assert [row["book_id"] for page in pages for row in page.json()] == pending_ids[::-1]
    assert pages[-1].json() == []
    dashboard = app_client.get("/api/dashboard/attention?limit=1").json()["metadata_proposals"]
    assert dashboard["count"] == 2
    assert dashboard["items"][0]["book_id"] == pending_ids[-1]

    # Approval can leave the informational proposal open, but it is no longer work.
    pending_matches[-1].status = "approved"
    await db.commit()
    assert len(app_client.get("/api/metadata/inbox").json()) == 1
    assert app_client.get("/api/dashboard/attention").json()["metadata_proposals"]["count"] == 1
