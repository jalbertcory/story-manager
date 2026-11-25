import json

import pytest
from sqlalchemy import select

from backend.app import models
from backend.app.services import story_recap


async def _make_book(db, title: str, *, series: str | None = "Saga", index: float | None = None) -> models.Book:
    slug = title.lower().replace(" ", "-")
    book = models.Book(
        title=title,
        author="Writer",
        series=series,
        series_index=index,
        source_type=models.SourceType.epub,
        immutable_path=f"library/{slug}-immutable.epub",
        current_path=f"library/{slug}.epub",
    )
    db.add(book)
    await db.commit()
    await db.refresh(book)
    return book


async def _configure_llm(db) -> None:
    db.add(models.AudiobookSettings(llm_provider="ollama", llm_base_url="http://llm.test", llm_model="tiny"))
    await db.commit()


@pytest.fixture
def fake_llm(monkeypatch, tmp_path):
    """Replace the model and the EPUB reader; record every prompt sent."""
    prompts: list[str] = []
    texts: dict[str, list[str]] = {}
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"epub")

    async def call(_settings, messages, response_schema=None):
        prompts.append(messages[0]["content"])
        return json.dumps({"recap": f"recap {len(prompts)}"})

    monkeypatch.setattr(story_recap, "_call_llm", call)
    monkeypatch.setattr(story_recap, "resolve_library_file", lambda path: epub)
    monkeypatch.setattr(story_recap, "_read_chapter_texts", lambda path: texts.get("chapters", ["Chapter 1\n" + "x" * 500]))
    return prompts, texts


def test_chunk_passages_packs_and_condenses():
    chunks = story_recap.chunk_passages(["a" * 40, "b" * 40, "", "c" * 300], limit=100)

    assert [len(chunk) for chunk in chunks][:1] == [82]
    assert len(chunks) == 2
    assert len(chunks[1]) <= 100
    assert chunks[1].startswith("c") and "[...]" in chunks[1]


def test_condensed_passage_keeps_opening_middle_and_end_inside_budget():
    passage = "A" * 200 + "B" * 200 + "C" * 200

    (chunk,) = story_recap.chunk_passages([passage], limit=100)
    sections = chunk.split("\n[...]\n")

    assert len(chunk) <= 100
    assert [set(section) for section in sections] == [{"A"}, {"B"}, {"C"}]


@pytest.mark.parametrize("limit", [1, 2, 14, 16, 17])
def test_overlong_passage_respects_small_positive_budgets(limit):
    (chunk,) = story_recap.chunk_passages(["opening " * 25], limit=limit)

    assert chunk.startswith("o")
    assert 0 < len(chunk) <= limit


@pytest.mark.parametrize("limit", [0, -1])
def test_nonpositive_budget_is_rejected(limit):
    with pytest.raises(ValueError, match="positive"):
        story_recap.chunk_passages(["text"], limit=limit)


@pytest.mark.asyncio
async def test_predecessors_follow_reading_order_and_skip_the_book_itself(db):
    third = await _make_book(db, "Third", index=3)
    first = await _make_book(db, "First", index=1)
    second = await _make_book(db, "Second", index=2)
    loner = await _make_book(db, "Loner", series=None)

    assert [book.id for book in await story_recap.series_predecessors(db, third)] == [first.id, second.id]
    assert await story_recap.series_predecessors(db, first) == []
    assert await story_recap.series_predecessors(db, loner) == []


@pytest.mark.asyncio
async def test_story_so_far_writes_book_recaps_once_and_goes_stale_on_new_text(db, fake_llm):
    prompts, _texts = fake_llm
    await _configure_llm(db)
    first = await _make_book(db, "First", index=1)
    second = await _make_book(db, "Second", index=2)
    third = await _make_book(db, "Third", index=3)
    progress: list[tuple[int, int, str]] = []

    async def report(current: int, total: int, detail: str) -> None:
        progress.append((current, total, detail))

    message = await story_recap.generate_recap(db, third.id, "story_so_far", progress=report)

    assert "2 earlier books" in message
    # Notes + recap for each earlier book, then the combined story.
    assert len(prompts) == 5
    assert "First" in prompts[-1] and "Second" in prompts[-1] and "say nothing about “Third”" in prompts[-1]
    assert progress[-1] == (3, 3, "Recap ready")
    rows = (await db.execute(select(models.StoryRecap).order_by(models.StoryRecap.id))).scalars().all()
    assert [(row.book_id, row.kind) for row in rows] == [
        (first.id, "book"),
        (second.id, "book"),
        (third.id, "story_so_far"),
    ]
    assert rows[2].covered_book_ids == [first.id, second.id]
    assert rows[2].llm_model == "tiny"
    assert (await story_recap.recap_state(db, third, "story_so_far")).stale is False

    # Regenerating reuses the cached book recaps: one combining request only.
    await story_recap.generate_recap(db, third.id, "story_so_far", force=True)
    assert len(prompts) == 6

    second.content_version += 1
    await db.commit()
    await db.refresh(third)
    assert (await story_recap.recap_state(db, third, "story_so_far")).stale is True
    assert (await story_recap.recap_state(db, second, "book")).stale is True

    await story_recap.generate_recap(db, third.id, "story_so_far")
    # Only the changed book is read again.
    assert len(prompts) == 9
    assert (await story_recap.recap_state(db, third, "story_so_far")).stale is False


@pytest.mark.asyncio
async def test_single_earlier_book_reuses_its_recap(db, fake_llm):
    prompts, _texts = fake_llm
    await _configure_llm(db)
    await _make_book(db, "First", index=1)
    second = await _make_book(db, "Second", index=2)

    await story_recap.generate_recap(db, second.id, "story_so_far")

    assert len(prompts) == 2
    state = await story_recap.recap_state(db, second, "story_so_far")
    assert state.recap is not None and state.recap.recap == "recap 2"


@pytest.mark.asyncio
async def test_book_recap_prefers_narration_chapter_summaries(db, fake_llm):
    prompts, _texts = fake_llm
    await _configure_llm(db)
    book = await _make_book(db, "First", index=1)
    book.audiobook_text_content_version = book.content_version
    db.add_all(
        [
            models.AudiobookChapter(book_id=book.id, chapter_number=1, content_file_name="a.xhtml", summary="Ann left."),
            models.AudiobookChapter(book_id=book.id, chapter_number=2, content_file_name="b.xhtml", summary="Ann won."),
        ]
    )
    await db.commit()

    await story_recap.generate_recap(db, book.id, "book")

    assert len(prompts) == 1
    assert "Ann left.\n\nAnn won." in prompts[0]


@pytest.mark.asyncio
async def test_long_books_are_read_in_chunks(db, fake_llm):
    prompts, texts = fake_llm
    texts["chapters"] = [f"Chapter {n}\n" + "y" * 15_000 for n in range(4)]
    await _configure_llm(db)
    book = await _make_book(db, "Long", index=1)

    await story_recap.generate_recap(db, book.id, "book")

    assert len(prompts) == 5


@pytest.mark.asyncio
async def test_recap_needs_a_language_model_and_earlier_books(db, fake_llm):
    book = await _make_book(db, "First", index=1)

    with pytest.raises(story_recap.RecapUnavailable, match="language model"):
        await story_recap.generate_recap(db, book.id, "book")

    await _configure_llm(db)
    with pytest.raises(story_recap.RecapUnavailable, match="no earlier books"):
        await story_recap.generate_recap(db, book.id, "story_so_far")


@pytest.mark.asyncio
async def test_recap_api(app_client, sqlite_sessionmaker, fake_llm):
    async with sqlite_sessionmaker() as db:
        first = await _make_book(db, "First", index=1)
        second = await _make_book(db, "Second", index=2)
        first_id, second_id = first.id, second.id
    url = f"/api/books/{second_id}/recap"

    body = app_client.get(url).json()
    assert body["llm_configured"] is False
    assert body["story_so_far"]["recap"] is None
    assert [book["title"] for book in body["story_so_far"]["covered_books"]] == ["First"]
    assert app_client.post(url, json={}).status_code == 409

    async with sqlite_sessionmaker() as db:
        await _configure_llm(db)
    assert app_client.post(f"/api/books/{first_id}/recap", json={"kind": "story_so_far"}).status_code == 409
    assert app_client.get("/api/books/999999/recap").status_code == 404

    queued = app_client.post(url, json={})
    assert queued.status_code == 202, queued.text
    assert queued.json()["job_type"] == "story_recap"
    assert app_client.post(url, json={}).json()["id"] == queued.json()["id"]
    assert app_client.get(url).json()["active_job"]["id"] == queued.json()["id"]

    async with sqlite_sessionmaker() as db:
        await story_recap.generate_recap(db, second_id, "story_so_far")
    body = app_client.get(url).json()
    assert body["story_so_far"]["recap"] == "recap 2"
    assert body["story_so_far"]["stale"] is False
    assert body["story_so_far"]["llm_model"] == "tiny"
