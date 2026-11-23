"""Story recaps: "previously in this series" reminders written by the LLM.

A ``book`` recap condenses one book. A ``story_so_far`` recap is written for a
reader about to open a book and covers every earlier book of its series; it is
composed from those books' own recaps, which are written once and reused.

Recaps deliberately contain spoilers for the books they cover and never for
the book the reader is about to start.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from bs4 import BeautifulSoup
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..epub_editor import get_chapters
from ..models import AudiobookChapter, AudiobookSettings, Book, StoryRecap
from .audiobook_llm import STUB_PROVIDER, _call_llm, _extract_json
from .endpoint_pool import configured_endpoints, primary_provider
from .library_paths import resolve_library_file

logger = logging.getLogger(__name__)

RecapKind = Literal["book", "story_so_far"]
ProgressCallback = Callable[[int, int, str], Awaitable[None]]

# One request's worth of story text. Sized for local models with a 32K context.
CHUNK_CHARS = 24_000
# Shorter documents are title pages, dedications and the like.
MIN_CHAPTER_CHARS = 400
MAX_RECAP_CHARS = 6_000

RECAP_SCHEMA = {
    "type": "object",
    "properties": {"recap": {"type": "string"}},
    "required": ["recap"],
    "additionalProperties": False,
}

_NOTES_PROMPT = (
    "You are preparing notes for a recap of a novel. Summarise what happens in the passage below in 4-8 "
    "plain sentences: events in order, who did what, what changed, and anything left unresolved. Name the "
    "characters. Use only this text and ignore front matter, tables of contents and author's notes. "
    "Return JSON with the key recap.\n\n"
)
_CONDENSE_PROMPT = (
    "Condense these consecutive plot notes from one novel into a shorter set of notes. Keep the order of "
    "events, every named character who matters later, and unresolved threads. Return JSON with the key recap.\n\n"
)
_BOOK_PROMPT = (
    "Write a recap of the novel {title} for a reader who finished it a while ago and is about to read the "
    "next book. In 3-5 short paragraphs cover the main characters and what they want, the important events "
    "in order, how the book ends, and the threads left open. Spoilers for this book are wanted. Use only "
    "the notes below; do not invent or add outside knowledge. Plain prose, no headings or lists. "
    "Return JSON with the key recap.\n\nNotes:\n"
)
_STORY_PROMPT = (
    "Write a “previously in {series}” recap for a reader about to start {title}. Combine the per-book "
    "recaps below, which are in reading order, into one account of the story so far in 3-6 short "
    "paragraphs: who the main characters are, the events that still matter, where everyone stood at the "
    "end of the latest book, and the open questions. Use only these recaps and say nothing about {title} "
    "itself. Plain prose, no headings or lists. Return JSON with the key recap.\n\n"
)


class RecapUnavailable(RuntimeError):
    """A recap cannot be written, for a reason the user can act on."""


class _RecapResponse(BaseModel):
    recap: str


@dataclass(frozen=True)
class RecapState:
    """What the book page shows about one kind of recap."""

    recap: StoryRecap | None
    stale: bool
    covered_books: list[Book]


def llm_configured(settings: AudiobookSettings | None) -> bool:
    if settings is None:
        return False
    return bool(configured_endpoints(settings, "llm")) or bool(settings.llm_provider)


def _provider(settings: AudiobookSettings | None) -> str:
    return primary_provider(settings, "llm", (settings.llm_provider if settings else None) or "").lower()


def book_fingerprint(book: Book) -> str:
    return f"book:{book.id}:v{book.content_version}"


def story_fingerprint(predecessors: Sequence[Book]) -> str:
    joined = "|".join(book_fingerprint(book) for book in predecessors)
    return hashlib.sha256(joined.encode()).hexdigest()


async def series_predecessors(db: AsyncSession, book: Book) -> list[Book]:
    """Readable books that come before this one in its series' reading order."""
    if not book.series:
        return []
    ordered = await crud.get_books_by_series(db, series=book.series, skip=0, limit=100_000)
    earlier: list[Book] = []
    for candidate in ordered:
        if candidate.id == book.id:
            return [item for item in earlier if item.current_path]
        earlier.append(candidate)
    return []


async def _stored(db: AsyncSession, book_id: int, kind: RecapKind) -> StoryRecap | None:
    result = await db.execute(select(StoryRecap).where(StoryRecap.book_id == book_id, StoryRecap.kind == kind))
    return result.scalar_one_or_none()


async def recap_state(db: AsyncSession, book: Book, kind: RecapKind) -> RecapState:
    recap = await _stored(db, book.id, kind)
    if kind == "book":
        return RecapState(recap, recap is not None and recap.source_fingerprint != book_fingerprint(book), [book])
    predecessors = await series_predecessors(db, book)
    stale = recap is not None and recap.source_fingerprint != story_fingerprint(predecessors)
    return RecapState(recap, stale, predecessors)


def _condense(text: str, limit: int) -> str:
    """Keep the opening, middle and ending of an over-long chapter."""
    if len(text) <= limit:
        return text
    part = limit // 3
    start = (len(text) - part) // 2
    end = start + part
    return "\n[...]\n".join([text[:part], text[start:end], text[-part:]])


def chunk_passages(passages: Sequence[str], limit: int = CHUNK_CHARS) -> list[str]:
    """Pack consecutive passages into requests of at most ``limit`` characters."""
    chunks: list[str] = []
    current: list[str] = []
    used = 0
    for passage in passages:
        text = _condense(passage.strip(), limit)
        if not text:
            continue
        if current and used + len(text) + 2 > limit:
            chunks.append("\n\n".join(current))
            current, used = [], 0
        current.append(text)
        used += len(text) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _read_chapter_texts(epub_path: str) -> list[str]:
    texts: list[str] = []
    for chapter in get_chapters(epub_path):
        text = BeautifulSoup(chapter["content"], "html.parser").get_text(" ", strip=True)
        if len(text) >= MIN_CHAPTER_CHARS:
            texts.append(f"{chapter['title']}\n{text}")
    return texts


async def _narration_chapter_summaries(db: AsyncSession, book: Book) -> list[str] | None:
    """Chapter summaries the narration pipeline already wrote for this exact text."""
    if book.audiobook_text_content_version != book.content_version:
        return None
    result = await db.execute(
        select(AudiobookChapter.summary).where(AudiobookChapter.book_id == book.id).order_by(AudiobookChapter.chapter_number)
    )
    summaries = [row[0] for row in result.all()]
    if not summaries or any(not (summary or "").strip() for summary in summaries):
        return None
    return [str(summary).strip() for summary in summaries]


async def _ask(settings: AudiobookSettings | None, prompt: str) -> str:
    if _provider(settings) == STUB_PROVIDER:
        # The local harness has no model; echo a bounded, deterministic digest.
        body = prompt.rsplit("\n\n", 1)[-1]
        return " ".join(body.split())[:400]
    if settings is None:
        raise RecapUnavailable("Set up a language model under Audio & AI Configuration to write recaps.")
    raw = await _call_llm(settings, [{"role": "user", "content": prompt}], response_schema=RECAP_SCHEMA)
    recap = _RecapResponse.model_validate(_extract_json(raw)).recap.strip()
    if not recap:
        raise RuntimeError("The language model returned an empty recap.")
    return recap


async def _fold_notes(settings: AudiobookSettings | None, notes: list[str]) -> str:
    """Condense notes until they fit in a single request."""
    while len("\n\n".join(notes)) > CHUNK_CHARS and len(notes) > 1:
        batches = chunk_passages(notes, CHUNK_CHARS)
        if len(batches) >= len(notes):
            break
        notes = [await _ask(settings, _CONDENSE_PROMPT + batch) for batch in batches]
    return _condense("\n\n".join(notes), CHUNK_CHARS)


async def _save(
    db: AsyncSession,
    book_id: int,
    kind: RecapKind,
    *,
    recap: str,
    fingerprint: str,
    covered: Sequence[int],
    settings: AudiobookSettings | None,
) -> StoryRecap:
    row = await _stored(db, book_id, kind)
    if row is None:
        row = StoryRecap(book_id=book_id, kind=kind, recap="", source_fingerprint="")
        db.add(row)
    row.recap = recap[:MAX_RECAP_CHARS]
    row.source_fingerprint = fingerprint
    row.covered_book_ids = list(covered)
    row.llm_model = settings.llm_model if settings else None
    row.updated_at = func.now()
    await db.commit()
    await db.refresh(row)
    return row


async def _write_book_recap(
    db: AsyncSession,
    settings: AudiobookSettings | None,
    book: Book,
    report: Callable[[str], Awaitable[None]],
) -> StoryRecap:
    label = book.title or f"book {book.id}"
    notes = await _narration_chapter_summaries(db, book)
    if notes is None:
        path = resolve_library_file(book.current_path)
        if path is None or not path.is_file():
            raise RecapUnavailable(f"“{label}” has no readable text to recap.")
        passages = await asyncio.to_thread(_read_chapter_texts, str(path))
        chunks = chunk_passages(passages)
        if not chunks:
            raise RecapUnavailable(f"“{label}” has no readable text to recap.")
        notes = []
        for index, chunk in enumerate(chunks, start=1):
            await report(f"Reading “{label}” ({index} of {len(chunks)})")
            notes.append(await _ask(settings, _NOTES_PROMPT + chunk))
    await report(f"Writing the recap of “{label}”")
    folded = await _fold_notes(settings, notes)
    recap = await _ask(settings, _BOOK_PROMPT.format(title=f"“{label}”") + folded)
    return await _save(
        db, book.id, "book", recap=recap, fingerprint=book_fingerprint(book), covered=[book.id], settings=settings
    )


async def generate_recap(
    db: AsyncSession,
    book_id: int,
    kind: RecapKind,
    *,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> str:
    """Write (or refresh) one recap and return a one-line result."""
    book = await db.get(Book, book_id)
    if book is None or book.deleted_at is not None:
        raise RecapUnavailable("This book is no longer in the library.")
    settings = await crud.audiobook.get_audiobook_settings(db)
    if not llm_configured(settings):
        raise RecapUnavailable("Set up a language model under Audio & AI Configuration to write recaps.")

    targets = [book] if kind == "book" else await series_predecessors(db, book)
    if not targets:
        raise RecapUnavailable("There are no earlier books in this series to recap.")

    total = len(targets) + (1 if kind == "story_so_far" else 0)
    done = 0

    async def report(detail: str) -> None:
        if progress is not None:
            await progress(done, total, detail)

    recaps: list[tuple[Book, StoryRecap]] = []
    for target in targets:
        existing = await _stored(db, target.id, "book")
        # ``force`` rewrites the requested recap, not every cached earlier book.
        reusable = existing is not None and existing.source_fingerprint == book_fingerprint(target)
        if reusable and existing is not None and not (force and kind == "book"):
            recaps.append((target, existing))
        else:
            recaps.append((target, await _write_book_recap(db, settings, target, report)))
        done += 1

    if kind == "book":
        return f"Wrote the recap of “{book.title}”."

    await report("Writing the story so far")
    if len(recaps) == 1:
        story = recaps[0][1].recap
    else:
        sections = "\n\n".join(
            f"Book {position}: {target.title}\n{recap.recap}" for position, (target, recap) in enumerate(recaps, start=1)
        )
        prompt = _STORY_PROMPT.format(series=book.series, title=f"“{book.title}”") + _condense(sections, CHUNK_CHARS)
        story = await _ask(settings, prompt)
    await _save(
        db,
        book.id,
        "story_so_far",
        recap=story,
        fingerprint=story_fingerprint(targets),
        covered=[target.id for target in targets],
        settings=settings,
    )
    done = total
    await report("Recap ready")
    return f"Wrote the story so far for “{book.title}” from {len(targets)} earlier book{'s' if len(targets) != 1 else ''}."
