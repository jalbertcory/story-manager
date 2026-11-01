"""Durable modular audiobook publication for authenticated Reader clients."""

from __future__ import annotations

import asyncio
import hashlib
import posixpath
import shutil
import stat
import tempfile
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from .. import crud
from ..config import LIBRARY_PATH
from .library_paths import book_audiobook_dir
from ..models import AudiobookChapter, Book
from ..lifecycle import (
    AUDIOBOOK_PUBLICATION,
    CHAPTER_GENERATION,
    AudiobookPublicationStatus,
    ChapterGenerationStatus,
    transition_state,
)


def normalize_resource_href(raw: str | None, chapter_number: int = 0) -> str:
    fallback = f"chapter{chapter_number:04d}.xhtml"
    value = (raw or fallback).replace("\\", "/").lstrip("/")
    return posixpath.normpath(value).removeprefix("./")


def stable_chapter_key(href: str) -> str:
    normalized = normalize_resource_href(href)
    return f"src-{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reader_smil_bytes(source: bytes, text_href: str) -> bytes:
    """Make SMIL references relative to the reader's rendition href.

    The Android reader parses the overlay using ``<text href>.smil`` as its
    logical base. Package SMIL files often repeat the full XHTML href, which
    would resolve to a duplicated directory under that base.
    """
    root = ET.fromstring(source)
    smil_namespace = "{http://www.w3.org/ns/SMIL}"
    normalized_href = normalize_resource_href(text_href)
    logical_smil_href = f"{normalized_href}.smil"
    base_dir = posixpath.dirname(logical_smil_href) or "."
    relative_text_href = posixpath.relpath(normalized_href, base_dir)
    for text in root.findall(f".//{smil_namespace}text"):
        fragment = text.attrib.get("src", "").partition("#")[2]
        text.set("src", f"{relative_text_href}#{fragment}" if fragment else relative_text_href)
    for audio in root.findall(f".//{smil_namespace}audio"):
        audio.set("src", "audio.mp3")
    ET.indent(root, space="  ")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")).encode("utf-8")


def _resolved(relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    candidate = (LIBRARY_PATH.parent / relative_path).resolve()
    try:
        candidate.relative_to(LIBRARY_PATH.parent.resolve())
    except ValueError:
        return None
    return candidate


def _matches(column: InstrumentedAttribute[str | None], value: str | None) -> ColumnElement[bool]:
    return column.is_(None) if value is None else column == value


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(LIBRARY_PATH.parent.resolve()))


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write(content: bytes, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def chapter_reader_audio_path(chapter: AudiobookChapter) -> Path | None:
    return _resolved(chapter.reader_audio_file_path or chapter.audio_file_path)


def chapter_reader_smil_path(chapter: AudiobookChapter) -> Path | None:
    return _resolved(chapter.reader_smil_file_path or chapter.smil_file_path)


@lru_cache(maxsize=256)
def _cached_reader_smil(path: str, mtime_ns: int, size: int, text_href: str) -> bytes:
    """Rewrite a SMIL file once per on-disk version; the stat fields only key the cache."""
    return reader_smil_bytes(Path(path).read_bytes(), text_href)


def chapter_reader_smil_bytes(chapter: AudiobookChapter) -> bytes | None:
    """Return the reader-ready SMIL. Blocking: call it through ``asyncio.to_thread``."""
    path = chapter_reader_smil_path(chapter)
    if path is None:
        return None
    try:
        info = path.stat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    text_href = chapter.source_href or chapter.content_file_name or ""
    return _cached_reader_smil(str(path), info.st_mtime_ns, info.st_size, text_href)


def text_reader_path(book: Book) -> Path | None:
    explicit = _resolved(book.audiobook_text_file_path)
    if explicit and explicit.is_file():
        return explicit
    legacy = book_audiobook_dir(book.id) / "working.epub"
    return legacy if legacy.is_file() else None


def stage_reader_text_rendition(book_id: int, content_version: int, source: Path) -> tuple[str, int, str]:
    """Atomically stage a versioned text rendition before its metadata commits."""
    target = book_audiobook_dir(book_id) / "reader" / f"text-v{content_version}.epub"
    _atomic_copy(source, target)
    return _relative(target), target.stat().st_size, sha256_file(target)


def _size_and_sha256(path: Path) -> tuple[int, str] | None:
    return (path.stat().st_size, sha256_file(path)) if path.is_file() else None


def _copy_and_checksum(source: Path, target: Path) -> tuple[int, str]:
    _atomic_copy(source, target)
    return target.stat().st_size, sha256_file(target)


async def publish_reader_audiobook(db: AsyncSession, book_id: int) -> None:
    """Publish verified text/audio/SMIL files, then commit visible metadata once."""
    book = await db.get(Book, book_id)
    if book is None:
        raise RuntimeError(f"Book {book_id} not found while publishing reader audiobook")
    chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    source_text = text_reader_path(book)
    if source_text is None or not source_text.is_file():
        raise RuntimeError(f"Reader text rendition is missing for book {book_id}")

    content_version = book.audiobook_source_content_version or book.content_version or 1
    publication_root = book_audiobook_dir(book_id) / "reader"
    text_target = publication_root / f"text-v{content_version}.epub"
    text_size, text_sha = await asyncio.to_thread(_copy_and_checksum, source_text, text_target)

    ready_count = 0
    for chapter in chapters:
        source_audio = _resolved(chapter.audio_file_path)
        source_smil = _resolved(chapter.smil_file_path)
        if source_audio is None or source_smil is None or not source_audio.is_file() or not source_smil.is_file():
            transition_state(
                chapter,
                "generation_state",
                CHAPTER_GENERATION,
                ChapterGenerationStatus.PENDING,
                context=f"audiobook chapter {chapter.id}",
            )
            continue

        href = normalize_resource_href(chapter.source_href or chapter.content_file_name, chapter.chapter_number)
        key = chapter.stable_chapter_key or stable_chapter_key(href)
        chapter.stable_chapter_key = key
        chapter.source_href = href
        audio_sha = await asyncio.to_thread(sha256_file, source_audio)
        smil_content = reader_smil_bytes(await asyncio.to_thread(source_smil.read_bytes), href)
        smil_sha = sha256_bytes(smil_content)
        changed = chapter.audio_sha256 != audio_sha or chapter.smil_sha256 != smil_sha
        revision = max(1, (chapter.audio_revision or 0) + int(changed))
        chapter_dir = publication_root / "chapters" / key
        audio_target = chapter_dir / f"audio-v{revision}.mp3"
        smil_target = chapter_dir / f"overlay-v{revision}.smil"
        if changed or not audio_target.is_file():
            await asyncio.to_thread(_atomic_copy, source_audio, audio_target)
        if changed or not smil_target.is_file():
            await asyncio.to_thread(_atomic_write, smil_content, smil_target)

        sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        chapter.audio_revision = revision
        chapter.reader_audio_file_path = _relative(audio_target)
        chapter.reader_smil_file_path = _relative(smil_target)
        chapter.audio_size_bytes = audio_target.stat().st_size
        chapter.audio_sha256 = audio_sha
        chapter.smil_size_bytes = len(smil_content)
        chapter.smil_sha256 = smil_sha
        chapter.duration_ms = sum(sentence.audio_duration_ms or 0 for sentence in sentences)
        transition_state(
            chapter,
            "generation_state",
            CHAPTER_GENERATION,
            ChapterGenerationStatus.READY,
            context=f"audiobook chapter {chapter.id}",
        )
        ready_count += 1

    book.audiobook_revision = (book.audiobook_revision or 0) + 1
    pending_content_version = max(
        book.audiobook_pending_content_version or 0,
        (book.content_version or content_version) if (book.content_version or content_version) > content_version else 0,
    )
    book.audiobook_source_content_version = content_version
    book.audiobook_text_content_version = content_version
    book.audiobook_pending_content_version = pending_content_version or None
    transition_state(
        book,
        "audiobook_publication_state",
        AUDIOBOOK_PUBLICATION,
        (
            AudiobookPublicationStatus.COMPLETE
            if chapters and ready_count == len(chapters) and not pending_content_version
            else AudiobookPublicationStatus.PARTIAL
        ),
        context=f"book {book.id}",
    )
    book.audiobook_text_file_path = _relative(text_target)
    book.audiobook_text_size_bytes = text_size
    book.audiobook_text_sha256 = text_sha
    book.audiobook_publication_error = None
    await db.commit()


async def backfill_reader_checksums(db: AsyncSession) -> int:
    """Fill the sizes and hashes that publications made before they were stored left null.

    The reader routes fall back to hashing files per request while these are null.
    Each update re-checks the null and the file paths so a concurrent publish wins.
    """
    filled = 0
    chapters = (
        (
            await db.execute(
                select(AudiobookChapter).where(
                    AudiobookChapter.generation_state == ChapterGenerationStatus.READY.value,
                    or_(
                        AudiobookChapter.audio_size_bytes.is_(None),
                        AudiobookChapter.audio_sha256.is_(None),
                        AudiobookChapter.smil_size_bytes.is_(None),
                        AudiobookChapter.smil_sha256.is_(None),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    for chapter in chapters:
        same_files = (
            AudiobookChapter.id == chapter.id,
            _matches(AudiobookChapter.audio_file_path, chapter.audio_file_path),
            _matches(AudiobookChapter.reader_audio_file_path, chapter.reader_audio_file_path),
            _matches(AudiobookChapter.smil_file_path, chapter.smil_file_path),
            _matches(AudiobookChapter.reader_smil_file_path, chapter.reader_smil_file_path),
        )
        audio_path = chapter_reader_audio_path(chapter)
        audio = await asyncio.to_thread(_size_and_sha256, audio_path) if audio_path else None
        if audio is not None and (chapter.audio_size_bytes is None or chapter.audio_sha256 is None):
            result = await db.execute(
                update(AudiobookChapter)
                .where(*same_files, or_(AudiobookChapter.audio_size_bytes.is_(None), AudiobookChapter.audio_sha256.is_(None)))
                .values(audio_size_bytes=audio[0], audio_sha256=audio[1])
                .execution_options(synchronize_session=False)
            )
            filled += int(bool(getattr(result, "rowcount", 0)))
        smil = await asyncio.to_thread(chapter_reader_smil_bytes, chapter)
        if smil is not None and (chapter.smil_size_bytes is None or chapter.smil_sha256 is None):
            result = await db.execute(
                update(AudiobookChapter)
                .where(*same_files, or_(AudiobookChapter.smil_size_bytes.is_(None), AudiobookChapter.smil_sha256.is_(None)))
                .values(smil_size_bytes=len(smil), smil_sha256=sha256_bytes(smil))
                .execution_options(synchronize_session=False)
            )
            filled += int(bool(getattr(result, "rowcount", 0)))
        await db.commit()

    books = (
        (
            await db.execute(
                select(Book).where(
                    Book.audiobook_text_file_path.is_not(None),
                    or_(Book.audiobook_text_size_bytes.is_(None), Book.audiobook_text_sha256.is_(None)),
                )
            )
        )
        .scalars()
        .all()
    )
    for book in books:
        text_path = _resolved(book.audiobook_text_file_path)
        text = await asyncio.to_thread(_size_and_sha256, text_path) if text_path else None
        if text is None:
            continue
        result = await db.execute(
            update(Book)
            .where(
                Book.id == book.id,
                Book.audiobook_text_file_path == book.audiobook_text_file_path,
                or_(Book.audiobook_text_size_bytes.is_(None), Book.audiobook_text_sha256.is_(None)),
            )
            .values(audiobook_text_size_bytes=text[0], audiobook_text_sha256=text[1])
            .execution_options(synchronize_session=False)
        )
        filled += int(bool(getattr(result, "rowcount", 0)))
        await db.commit()
    return filled
