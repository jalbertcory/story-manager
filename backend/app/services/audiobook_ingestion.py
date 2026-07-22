"""Phase 1: EPUB ingestion, sentence tokenization, and span ID injection."""

from __future__ import annotations

import hashlib
import logging
import shutil
import tempfile
from collections import Counter
from pathlib import Path

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, NavigableString
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..models import AudiobookChapter, AudiobookSentence, Book
from .audiobook_publication import (
    normalize_resource_href,
    stable_chapter_key,
    stage_reader_text_rendition,
)

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


def _stable_sentence_id(chapter_key: str, text: str, occurrence: int) -> str:
    normalized = " ".join(text.split()).casefold()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{chapter_key}-{digest}-{occurrence}"


def _inject_spans_into_text_node(
    text_node: NavigableString,
    chapter_key: str,
    start_seq: int,
    occurrences: Counter[str],
    existing_ids: list[str] | None = None,
) -> tuple[int, list[dict]]:
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
        normalized = " ".join(sent_text.split()).casefold()
        occurrence = occurrences[normalized]
        occurrences[normalized] += 1
        span_id = (
            existing_ids[seq]
            if existing_ids is not None and seq < len(existing_ids)
            else _stable_sentence_id(chapter_key, sent_text, occurrence)
        )
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


def _source_content_hash(soup: BeautifulSoup) -> str:
    return hashlib.sha256(str(soup).encode("utf-8")).hexdigest()


def _chapter_title(item, soup: BeautifulSoup, chapter_number: int) -> str:
    title = (getattr(item, "title", None) or "").strip()
    if title:
        return title
    heading = soup.find(["h1", "h2", "h3"])
    if heading:
        value = heading.get_text(" ", strip=True)
        if value:
            return value[:500]
    return f"Chapter {chapter_number}"


def _sentence_texts(soup: BeautifulSoup) -> list[str]:
    texts: list[str] = []
    container = soup.body or soup
    for text_node in list(container.find_all(string=True)):
        stripped = str(text_node).strip()
        if stripped and not _should_skip_text_node(text_node):
            texts.extend(_tokenize_text(stripped))
    return texts


def _chapter_artifact_paths(chapter: AudiobookChapter, sentences: list[AudiobookSentence]) -> set[Path]:
    paths: set[Path] = set()
    for relative_path in (
        chapter.audio_file_path,
        chapter.smil_file_path,
        chapter.reader_audio_file_path,
        chapter.reader_smil_file_path,
        *(sentence.audio_file_path for sentence in sentences),
    ):
        if relative_path:
            path = (LIBRARY_PATH.parent / relative_path).resolve()
            if path.is_relative_to(LIBRARY_PATH.parent.resolve()):
                paths.add(path)
    return paths


async def ingest_epub(book_id: int, db: AsyncSession) -> None:
    """Diff the current EPUB into stable chapters and publish its text rendition."""
    book: Book = await db.get(Book, book_id)
    if book is None:
        raise ValueError(f"Book {book_id} not found")

    epub_path = (LIBRARY_PATH.parent / book.current_path).resolve()
    ingested_content_version = book.content_version or 1
    logger.info("Ingesting EPUB for book %s from %s", book_id, epub_path)

    output_dir = LIBRARY_PATH.parent / "library" / "audiobooks" / str(book_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    snippets_dir = output_dir / "snippets"
    snippets_dir.mkdir(exist_ok=True)

    with tempfile.NamedTemporaryFile(dir=output_dir, suffix=".source.epub", delete=False) as handle:
        source_snapshot = Path(handle.name)
    try:
        shutil.copyfile(epub_path, source_snapshot)
        ebook = epub.read_epub(str(source_snapshot))
    finally:
        source_snapshot.unlink(missing_ok=True)
    existing_chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    existing_chapter_ids = {chapter.id for chapter in existing_chapters}
    existing_sentences = {
        chapter.id: await crud.audiobook.get_sentences_for_chapter(db, chapter.id) for chapter in existing_chapters
    }
    by_href = {
        normalize_resource_href(chapter.source_href or chapter.content_file_name, chapter.chapter_number): chapter
        for chapter in existing_chapters
    }
    by_hash: dict[str, list[AudiobookChapter]] = {}
    for chapter in existing_chapters:
        if chapter.source_content_hash:
            by_hash.setdefault(chapter.source_content_hash, []).append(chapter)

    # Collect spine items in order
    spine_items = []
    for item_id, _linear in ebook.spine:
        item = ebook.get_item_with_id(item_id)
        if item and item.get_type() == ebooklib.ITEM_DOCUMENT and not isinstance(item, epub.EpubNav):
            spine_items.append(item)

    all_chapter_records = []
    matched_ids: set[int] = set()
    used_keys = {chapter.stable_chapter_key for chapter in existing_chapters if chapter.stable_chapter_key}
    changed_chapter_ids: set[int] = set()
    new_chapter_count = 0
    obsolete_paths: set[Path] = set()

    for chapter_num, item in enumerate(spine_items, start=1):
        content = item.get_content()
        soup = BeautifulSoup(content, "html.parser")
        href = normalize_resource_href(item.get_name(), chapter_num)
        content_hash = _source_content_hash(soup)
        sentence_texts = _sentence_texts(soup)

        chapter = by_href.get(href)
        if chapter is not None and chapter.id in matched_ids:
            chapter = None
        if chapter is None:
            chapter = next(
                (candidate for candidate in by_hash.get(content_hash, []) if candidate.id not in matched_ids),
                None,
            )

        if chapter is None:
            base_key = stable_chapter_key(href)
            key = base_key
            suffix = 2
            while key in used_keys:
                key = f"{base_key}-{suffix}"
                suffix += 1
            used_keys.add(key)
            chapter = AudiobookChapter(
                book_id=book_id,
                chapter_number=chapter_num,
                content_file_name=href,
                stable_chapter_key=key,
                source_href=href,
                source_content_hash=content_hash,
                title=_chapter_title(item, soup, chapter_num),
                spine_order=chapter_num - 1,
                generation_state="pending",
                needs_reassembly=True,
            )
            db.add(chapter)
            await db.flush()
            previous_sentences: list[AudiobookSentence] = []
            unchanged = False
            new_chapter_count += 1
        else:
            matched_ids.add(chapter.id)
            previous_sentences = existing_sentences[chapter.id]
            unchanged = chapter.source_content_hash == content_hash or (
                chapter.source_content_hash is None
                and [sentence.original_text for sentence in previous_sentences] == sentence_texts
            )
            if not unchanged:
                changed_chapter_ids.add(chapter.id)

        key = chapter.stable_chapter_key or stable_chapter_key(href)
        existing_ids = [sentence.html_element_id for sentence in previous_sentences] if unchanged else None

        chapter_sentences: list[dict] = []
        seq = 0
        occurrences: Counter[str] = Counter()

        # Process text nodes in document order. This preserves existing block and
        # inline structure while adding stable sentence-level anchors.
        container = soup.body or soup
        for text_node in list(container.find_all(string=True)):
            seq, new_sentences = _inject_spans_into_text_node(
                text_node,
                key,
                seq,
                occurrences,
                existing_ids,
            )
            chapter_sentences.extend(new_sentences)

        # Save modified XHTML back into the ebook item
        item.set_content(str(soup).encode("utf-8"))
        if not chapter_sentences:
            if chapter.id not in existing_chapter_ids:
                await db.delete(chapter)
            continue

        chapter.chapter_number = chapter_num
        chapter.content_file_name = href
        chapter.stable_chapter_key = key
        chapter.source_href = href
        chapter.source_content_hash = content_hash
        chapter.title = _chapter_title(item, soup, chapter_num)
        chapter.spine_order = chapter_num - 1

        if not unchanged:
            obsolete_paths.update(_chapter_artifact_paths(chapter, previous_sentences))
            for sentence in previous_sentences:
                await db.delete(sentence)
            chapter.audio_file_path = None
            chapter.smil_file_path = None
            chapter.reader_audio_file_path = None
            chapter.reader_smil_file_path = None
            chapter.audio_size_bytes = None
            chapter.audio_sha256 = None
            chapter.smil_size_bytes = None
            chapter.smil_sha256 = None
            chapter.duration_ms = None
            chapter.needs_reassembly = True
            chapter.generation_state = "pending"
            chapter.summary = None
            chapter.summary_updated_at = None
            db.add_all([AudiobookSentence(chapter_id=chapter.id, **sentence) for sentence in chapter_sentences])
        all_chapter_records.append((chapter, unchanged))

    # Write modified EPUB to working copy
    working_epub_path = output_dir / "working.epub"
    _ensure_toc_link_ids(ebook.toc)
    with tempfile.NamedTemporaryFile(dir=output_dir, suffix=".epub", delete=False) as handle:
        temporary_epub = Path(handle.name)
    try:
        epub.write_epub(str(temporary_epub), ebook)
        temporary_epub.replace(working_epub_path)
    finally:
        temporary_epub.unlink(missing_ok=True)
    logger.info("Wrote span-injected EPUB to %s", working_epub_path)

    retained_existing_ids = {chapter.id for chapter, _unchanged in all_chapter_records if chapter.id in existing_chapter_ids}
    removed_chapters = [chapter for chapter in existing_chapters if chapter.id not in retained_existing_ids]
    for chapter in removed_chapters:
        obsolete_paths.update(_chapter_artifact_paths(chapter, existing_sentences[chapter.id]))
        await db.delete(chapter)

    persisted_chapters = len(all_chapter_records)
    if persisted_chapters == 0:
        await db.rollback()
        raise RuntimeError(f"EPUB for book {book_id} contains no narratable text.")

    text_path, text_size, text_sha = stage_reader_text_rendition(
        book_id,
        ingested_content_version,
        working_epub_path,
    )
    await db.refresh(
        book,
        attribute_names=["content_version", "audiobook_pending_content_version"],
    )
    latest_content_version = book.content_version or ingested_content_version
    characters = await crud.audiobook.get_characters_for_book(db, book_id)
    ready_count = sum(1 for chapter, _ in all_chapter_records if chapter.generation_state == "ready")
    book.audiobook_revision = (book.audiobook_revision or 0) + 1
    book.audiobook_source_content_version = ingested_content_version
    book.audiobook_text_content_version = ingested_content_version
    book.audiobook_pending_content_version = (
        latest_content_version if latest_content_version > ingested_content_version else None
    )
    book.audiobook_text_file_path = text_path
    book.audiobook_text_size_bytes = text_size
    book.audiobook_text_sha256 = text_sha
    book.audiobook_publication_state = "partial" if ready_count else "processing"
    book.audiobook_publication_error = None
    book.audiobook_pipeline_status = "diarizing" if characters else "roster_gen"
    book.audiobook_progress_current = persisted_chapters
    book.audiobook_progress_total = persisted_chapters
    book.audiobook_progress_detail = (
        f"Ingested {persisted_chapters} sections: {new_chapter_count} new, "
        f"{len(changed_chapter_ids)} changed, {len(removed_chapters)} removed"
    )
    await db.commit()
    for path in obsolete_paths:
        path.unlink(missing_ok=True)
    (output_dir / "audiobook.epub").unlink(missing_ok=True)
    logger.info(
        "Ingestion complete for book %s: %d sections (%d new, %d changed, %d removed)",
        book_id,
        persisted_chapters,
        new_chapter_count,
        len(changed_chapter_ids),
        len(removed_chapters),
    )
