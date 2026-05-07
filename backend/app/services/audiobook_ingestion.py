"""Phase 1: EPUB ingestion, sentence tokenization, and span ID injection."""

from __future__ import annotations

import logging

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, NavigableString
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..models import Book

logger = logging.getLogger(__name__)

_NLP = None  # lazy-load spaCy model to avoid startup cost


def _get_nlp():
    global _NLP
    if _NLP is None:
        import spacy

        _NLP = spacy.load("en_core_web_sm", disable=["ner", "parser"])
        _NLP.add_pipe("sentencizer")
    return _NLP


def _tokenize_text(text: str) -> list[str]:
    nlp = _get_nlp()
    doc = nlp(text)
    return [sent.text.strip() for sent in doc.sents if sent.text.strip()]


def _inject_spans_into_element(element, chapter_num: int, start_seq: int) -> tuple[int, list[dict]]:
    """Replace the text content of block elements with span-wrapped sentences.

    Returns (next_sequence_number, list_of_sentence_dicts).
    """
    sentences_data = []
    seq = start_seq

    # Collect all text nodes that are direct or shallow children
    raw_text = element.get_text(separator=" ", strip=True)
    if not raw_text:
        return seq, sentences_data

    sentences = _tokenize_text(raw_text)
    if not sentences:
        return seq, sentences_data

    # Clear existing children and re-build with span-wrapped sentences
    element.clear()
    for sent_text in sentences:
        span_id = f"ch{chapter_num}_s{seq}"
        span = BeautifulSoup(f'<span id="{span_id}"></span>', "html.parser").find("span")
        span.string = sent_text
        element.append(span)
        element.append(NavigableString(" "))

        sentences_data.append(
            {
                "html_element_id": span_id,
                "sequence_order": seq,
                "original_text": sent_text,
                "tagged_text": sent_text,
                "status": "pending_diarization",
            }
        )
        seq += 1

    return seq, sentences_data


async def ingest_epub(book_id: int, db: AsyncSession) -> None:
    """Parse the book's EPUB, inject span IDs, populate chapters and sentences tables."""
    book: Book = await db.get(Book, book_id)
    if book is None:
        raise ValueError(f"Book {book_id} not found")

    epub_path = (LIBRARY_PATH.parent / book.current_path).resolve()
    logger.info("Ingesting EPUB for book %s from %s", book_id, epub_path)

    output_dir = LIBRARY_PATH.parent / "library" / "audiobooks" / str(book_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    snippets_dir = output_dir / "snippets"
    snippets_dir.mkdir(exist_ok=True)

    ebook = epub.read_epub(str(epub_path))

    # Collect spine items in order
    spine_items = []
    for item_id, _linear in ebook.spine:
        item = ebook.get_item_with_id(item_id)
        if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
            spine_items.append(item)

    all_chapter_records = []

    for chapter_num, item in enumerate(spine_items, start=1):
        content = item.get_content()
        soup = BeautifulSoup(content, "html.parser")

        chapter_sentences: list[dict] = []
        seq = 0

        # Process block-level text elements
        for tag in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"]):
            # Skip elements with no direct text (only child elements)
            if not tag.get_text(strip=True):
                continue
            # Skip if already contains span children from a previous run
            if tag.find("span", id=True):
                continue
            seq, new_sentences = _inject_spans_into_element(tag, chapter_num, seq)
            chapter_sentences.extend(new_sentences)

        # Save modified XHTML back into the ebook item
        item.set_content(str(soup).encode("utf-8"))
        all_chapter_records.append((chapter_num, item, chapter_sentences))

    # Write modified EPUB to working copy
    working_epub_path = output_dir / "working.epub"
    epub.write_epub(str(working_epub_path), ebook)
    logger.info("Wrote span-injected EPUB to %s", working_epub_path)

    # Persist to database
    for chapter_num, _item, chapter_sentences in all_chapter_records:
        if not chapter_sentences:
            continue
        chapter = await crud.audiobook.create_chapter(db, book_id=book_id, chapter_number=chapter_num)
        await crud.audiobook.create_sentences_bulk(db, chapter_id=chapter.id, sentences_data=chapter_sentences)

    await db.commit()
    await crud.audiobook.set_book_pipeline_status(db, book_id, "roster_gen")
    logger.info("Ingestion complete for book %s: %d chapters processed", book_id, len(all_chapter_records))
