from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.app import crud, models
from backend.app.services import audiobook_pronunciation, audiobook_tts
from backend.app.services.audiobook_pronunciation import Lexicon, PronunciationRule


def _rule(term: str, spoken: str, case_sensitive: bool = False) -> PronunciationRule:
    return PronunciationRule(term=term, spoken=spoken, case_sensitive=case_sensitive)


async def _make_book(db, title: str = "Audio Book", series: str | None = None) -> models.Book:
    slug = title.lower().replace(" ", "-")
    book = models.Book(
        title=title,
        author="Reader",
        series=series,
        audiobook_enabled=True,
        source_type=models.SourceType.epub,
        immutable_path=f"library/{slug}-immutable.epub",
        current_path=f"library/{slug}.epub",
    )
    db.add(book)
    await db.commit()
    await db.refresh(book)
    return book


async def _seed_chapter(db, book_id: int, texts: list[str], *, status: str = "audio_generated"):
    chapter = await crud.audiobook.create_chapter(
        db, book_id=book_id, chapter_number=1, content_file_name="Text/chapter_1.xhtml"
    )
    characters = await crud.audiobook.create_characters_bulk(
        db,
        book_id=book_id,
        characters_data=[{"name": "Narrator", "description": "Narrator", "voice_prompt": "[calm]", "is_narrator": True}],
    )
    await crud.audiobook.create_sentences_bulk(
        db,
        chapter_id=chapter.id,
        sentences_data=[
            {
                "html_element_id": f"ch1_s{index}",
                "sequence_order": index,
                "original_text": text,
                "tagged_text": text,
                "character_id": characters[0].id,
                "status": status,
                "audio_file_path": f"clips/{index}.mp3" if status == "audio_generated" else None,
            }
            for index, text in enumerate(texts)
        ],
    )
    return chapter


def test_lexicon_replaces_whole_words_only():
    lexicon = Lexicon([_rule("Cian", "KEE-an")])

    assert lexicon.apply("Cian met Cianna. cian's sword, (Cian)!") == "KEE-an met Cianna. KEE-an's sword, (KEE-an)!"
    assert lexicon.changes("Where is Cian?")
    assert not lexicon.changes("Cianna alone.")


def test_lexicon_prefers_longest_term_and_never_rewrites_its_own_output():
    lexicon = Lexicon([_rule("Kael", "Kale"), _rule("Kael Sun", "Kale Soon"), _rule("Kale", "WRONG")])

    assert lexicon.apply("Kael  Sun and Kael.") == "Kale Soon and Kale."


def test_lexicon_respects_case_sensitivity():
    lexicon = Lexicon([_rule("Will", "Wil", case_sensitive=True)])

    assert lexicon.apply("Will will go.") == "Wil will go."


def test_lexicon_leaves_expression_tags_alone():
    lexicon = Lexicon([_rule("laughter", "LAFF-ter")])

    assert lexicon.apply("[laughter] Such laughter.") == "[laughter] Such LAFF-ter."
    assert not lexicon.changes("[laughter] Quiet.")


def test_lexicon_handles_punctuated_terms_and_empty_rules():
    assert Lexicon([_rule("Xal'atath", "zal-uh-TATH")]).apply("Xal'atath spoke.") == "zal-uh-TATH spoke."
    assert Lexicon([_rule("  ", "x"), _rule("x", " ")]).apply("x") == "x"
    assert not Lexicon()


@pytest.mark.asyncio
async def test_book_rule_overrides_series_rule_which_overrides_global(db):
    book = await _make_book(db, series="Saga")
    other = await _make_book(db, title="Other Book")
    db.add_all(
        [
            models.AudiobookPronunciation(term="Cian", spoken="global"),
            models.AudiobookPronunciation(series_name="saga", term="cian", spoken="series"),
            models.AudiobookPronunciation(book_id=book.id, term="Cian", spoken="book"),
            models.AudiobookPronunciation(series_name="Saga", term="Aoife", spoken="EE-fa"),
        ]
    )
    await db.commit()

    lexicon = await audiobook_pronunciation.load_book_lexicon(db, book.id)
    assert lexicon.apply("Cian and Aoife") == "book and EE-fa"
    other_lexicon = await audiobook_pronunciation.load_book_lexicon(db, other.id)
    assert other_lexicon.apply("Cian and Aoife") == "global and Aoife"


@pytest.mark.asyncio
async def test_tts_requests_carry_respelling_but_stored_text_is_untouched(db):
    book = await _make_book(db)
    chapter = await _seed_chapter(db, book.id, ["Cian waited."], status="ready_for_audio")
    db.add(models.AudiobookPronunciation(book_id=book.id, term="Cian", spoken="KEE-an"))
    await db.commit()
    sentence = (await crud.audiobook.get_sentences_for_chapter(db, chapter.id))[0]

    requests = await audiobook_tts._build_sentence_requests(SimpleNamespace(), sentence, db)

    assert [request.text for request in requests] == ["KEE-an waited."]
    assert sentence.original_text == "Cian waited."


@pytest.mark.asyncio
async def test_regenerate_resets_only_narrated_sentences_with_the_term(db):
    book = await _make_book(db)
    chapter = await _seed_chapter(db, book.id, ["Cian waited.", "Nobody came.", "Cianna left."])

    reset = await audiobook_pronunciation.regenerate_sentences_with_terms(db, [book.id], [_rule("Cian", "KEE-an")])

    assert reset == 1
    sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
    for sentence in sentences:
        await db.refresh(sentence)
    assert [sentence.status for sentence in sentences] == ["ready_for_audio", "audio_generated", "audio_generated"]
    assert sentences[0].audio_file_path is None
    await db.refresh(chapter)
    assert chapter.needs_reassembly is True


@pytest.mark.asyncio
async def test_pronunciation_api_round_trip(app_client, sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        book = await _make_book(db, series="Saga")
        await _seed_chapter(db, book.id, ["Cian waited.", "Nobody came."])
        book_id = book.id
    base = f"/api/books/{book_id}/audiobook/pronunciations"

    created = app_client.post(base, json={"term": " Cian ", "spoken": "KEE-an", "scope": "series"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["sentences_reset"] == 0
    assert body["rule"]["scope"] == "series"
    assert body["rule"]["series_name"] == "Saga"
    assert body["rule"]["term"] == "Cian"
    assert body["rule"]["sentence_count"] == 1
    series_rule_id = body["rule"]["id"]

    assert app_client.post(base, json={"term": "cian", "spoken": "x", "scope": "series"}).status_code == 409

    override = app_client.post(base, json={"term": "Cian", "spoken": "KY-an", "scope": "book", "regenerate": True})
    assert override.status_code == 201, override.text
    assert override.json()["sentences_reset"] == 1
    assert override.json()["books_affected"] == 1

    listing = app_client.get(base).json()
    assert listing["series_name"] == "Saga"
    assert {(rule["scope"], rule["active"]) for rule in listing["rules"]} == {("series", False), ("book", True)}

    updated = app_client.put(f"/api/audiobook/pronunciations/{series_rule_id}", json={"spoken": "KEE-in"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["rule"]["spoken"] == "KEE-in"

    assert app_client.put(f"/api/audiobook/pronunciations/{series_rule_id}", json={"spoken": "  "}).status_code == 422
    assert app_client.delete(f"/api/audiobook/pronunciations/{series_rule_id}").status_code == 200
    assert app_client.delete(f"/api/audiobook/pronunciations/{series_rule_id}").status_code == 404
    assert len(app_client.get(base).json()["rules"]) == 1


@pytest.mark.asyncio
async def test_series_scope_needs_a_series(app_client, sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        book = await _make_book(db)
        await _seed_chapter(db, book.id, ["Cian waited."])
        book_id = book.id

    response = app_client.post(
        f"/api/books/{book_id}/audiobook/pronunciations", json={"term": "Cian", "spoken": "KEE-an", "scope": "series"}
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_series_rename_carries_pronunciations(db):
    await _make_book(db, series="Old Saga")
    await _make_book(db, title="Second", series="New Saga")
    db.add_all(
        [
            models.AudiobookPronunciation(series_name="Old Saga", term="Cian", spoken="old"),
            models.AudiobookPronunciation(series_name="Old Saga", term="Aoife", spoken="EE-fa"),
            models.AudiobookPronunciation(series_name="New Saga", term="cian", spoken="new"),
        ]
    )
    await db.commit()

    await crud.series.merge_series(db, "Old Saga", "New Saga")

    rules = (await db.execute(select(models.AudiobookPronunciation))).scalars().all()
    assert sorted((rule.series_name, rule.term, rule.spoken) for rule in rules) == [
        ("New Saga", "Aoife", "EE-fa"),
        ("New Saga", "cian", "new"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("existing_lock", "fail"),
    [(None, False), (None, True), ("stub", False)],
    ids=["first-preview", "failed-preview", "inherits-existing-provider"],
)
async def test_preview_never_persists_provider_locks(app_client, sqlite_sessionmaker, monkeypatch, existing_lock, fail):
    from backend.app.routers import audiobook_pronunciations

    async with sqlite_sessionmaker() as db:
        first = await _make_book(db, "Synthetic One", "Synthetic Series")
        second = await _make_book(db, "Synthetic Two", "synthetic series")
        ids = (first.id, second.id)
        second.audiobook_tts_provider = existing_lock
        await db.commit()

    requests = []

    async def fake_synthesize(settings, request):
        assert settings is None
        requests.append(request)
        if fail:
            raise RuntimeError("synthetic provider failure")
        return b"synthetic-audio"

    monkeypatch.setattr(audiobook_pronunciations, "synthesize_speech", fake_synthesize)
    if existing_lock:
        # With no provider settings, this deliberately unusable default would
        # reject the request unless preview inherits the sibling's stub lock.
        monkeypatch.setattr(audiobook_pronunciations, "tts_provider_name", lambda _: "unused-default")
    response = app_client.post(f"/api/books/{ids[0]}/audiobook/pronunciations/preview", json={"text": " KEE-an "})
    assert response.status_code == (502 if fail else 200), response.text
    assert [request.text for request in requests] == ["KEE-an"]
    if not fail:
        assert response.content == b"synthetic-audio"

    async with sqlite_sessionmaker() as db:
        books = [await db.get(models.Book, book_id) for book_id in ids]
        assert [book.audiobook_tts_provider for book in books] == [None, existing_lock]
