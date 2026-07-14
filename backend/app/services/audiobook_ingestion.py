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
_SKIP_TEXT_ANCESTORS = {"script", "style", "head", "title", "svg", "math", "audio", "video"}


def _get_nlp():
    global _NLP
    if _NLP is None:
        import spacy

        try:
            _NLP = spacy.load("en_core_web_sm", disable=["ner", "parser"])
        except OSError:
            logger.warning("spaCy model en_core_web_sm is unavailable; using the built-in English tokenizer.")
            _NLP = spacy.blank("en")
        if "sentencizer" not in _NLP.pipe_names:
            _NLP.add_pipe("sentencizer")
    return _NLP


def _tokenize_text(text: str) -> list[str]:
    nlp = _get_nlp()
    doc = nlp(text)
    return [sent.text.strip() for sent in doc.sents if sent.text.strip()]


def _span_for_sentence(span_id: str, text: str):
    span = BeautifulSoup(f'<span id="{span_id}"></span>', "html.parser").find("span")
    span.string = text
    return span


def _replace_text_node(text_node: NavigableString, replacement_nodes: list) -> None:
    first, *rest = replacement_nodes
    text_node.replace_with(first)
    previous = first
    for node in rest:
        previous.insert_after(node)
        previous = node


def _should_skip_text_node(text_node: NavigableString) -> bool:
    for parent in text_node.parents:
        if parent.name in _SKIP_TEXT_ANCESTORS:
            return True
        if parent.name == "span" and parent.get("id"):
            return True
    return False


def _ensure_toc_link_ids(toc_items, prefix: str = "toc") -> None:
    for index, item in enumerate(toc_items or []):
        uid = f"{prefix}_{index}"
        if isinstance(item, epub.Link) and not item.uid:
            item.uid = uid
        elif isinstance(item, (tuple, list)) and item:
            section = item[0]
            if isinstance(section, epub.Link) and not section.uid:
                section.uid = uid
            if len(item) > 1:
                _ensure_toc_link_ids(item[1], uid)


def _inject_spans_into_text_node(text_node: NavigableString, chapter_num: int, start_seq: int) -> tuple[int, list[dict]]:
    """Wrap one text node's sentences without disturbing surrounding markup.

    Returns (next_sequence_number, list_of_sentence_dicts).
    """
    sentences_data = []
    seq = start_seq

    raw_text = str(text_node)
    stripped = raw_text.strip()
    if not stripped or _should_skip_text_node(text_node):
        return seq, sentences_data

    sentences = _tokenize_text(stripped)
    if not sentences:
        return seq, sentences_data

    leading_whitespace = raw_text[: len(raw_text) - len(raw_text.lstrip())]
    trailing_start = len(raw_text.rstrip())
    trailing_whitespace = raw_text[trailing_start:]
    replacement_nodes: list = []
    if leading_whitespace:
        replacement_nodes.append(NavigableString(leading_whitespace))

    for index, sent_text in enumerate(sentences):
        if index > 0:
            replacement_nodes.append(NavigableString(" "))
        span_id = f"ch{chapter_num}_s{seq}"
        replacement_nodes.append(_span_for_sentence(span_id, sent_text))

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

    if trailing_whitespace:
        replacement_nodes.append(NavigableString(trailing_whitespace))

    _replace_text_node(text_node, replacement_nodes)
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
    await crud.audiobook.delete_chapters_for_book(db, book_id)
    await crud.audiobook.delete_characters_for_book(db, book_id)

    # Collect spine items in order
    spine_items = []
    for item_id, _linear in ebook.spine:
        item = ebook.get_item_with_id(item_id)
        if item and item.get_type() == ebooklib.ITEM_DOCUMENT and not isinstance(item, epub.EpubNav):
            spine_items.append(item)

    all_chapter_records = []

    for chapter_num, item in enumerate(spine_items, start=1):
        content = item.get_content()
        soup = BeautifulSoup(content, "html.parser")

        chapter_sentences: list[dict] = []
        seq = 0

        # Process text nodes in document order. This preserves existing block and
        # inline structure while adding stable sentence-level anchors.
        container = soup.body or soup
        for text_node in list(container.find_all(string=True)):
            seq, new_sentences = _inject_spans_into_text_node(text_node, chapter_num, seq)
            chapter_sentences.extend(new_sentences)

        # Save modified XHTML back into the ebook item
        item.set_content(str(soup).encode("utf-8"))
        all_chapter_records.append((chapter_num, item, chapter_sentences))

    # Write modified EPUB to working copy
    working_epub_path = output_dir / "working.epub"
    _ensure_toc_link_ids(ebook.toc)
    epub.write_epub(str(working_epub_path), ebook)
    logger.info("Wrote span-injected EPUB to %s", working_epub_path)

    # Persist to database
    persisted_chapters = 0
    total_chapters = sum(1 for _chapter_num, _item, sentences in all_chapter_records if sentences)
    await crud.audiobook.update_book_pipeline_progress(
        db,
        book_id,
        current=0,
        total=total_chapters,
        detail=f"Tokenized EPUB; saving {total_chapters} narratable sections",
    )
    for chapter_num, item, chapter_sentences in all_chapter_records:
        if not chapter_sentences:
            continue
        chapter = await crud.audiobook.create_chapter(
            db,
            book_id=book_id,
            chapter_number=chapter_num,
            content_file_name=item.get_name(),
        )
        await crud.audiobook.create_sentences_bulk(db, chapter_id=chapter.id, sentences_data=chapter_sentences)
        persisted_chapters += 1
        await crud.audiobook.update_book_pipeline_progress(
            db,
            book_id,
            current=persisted_chapters,
            total=total_chapters,
            detail=f"Saved section {persisted_chapters} of {total_chapters}",
        )

    await db.commit()
    if persisted_chapters == 0:
        raise RuntimeError(f"EPUB for book {book_id} contains no narratable text.")
    if not await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
        await crud.audiobook.set_book_pipeline_status(db, book_id, "roster_gen")
    logger.info("Ingestion complete for book %s: %d chapters processed", book_id, persisted_chapters)
