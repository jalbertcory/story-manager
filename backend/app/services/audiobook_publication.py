"""Durable modular audiobook publication for authenticated Reader clients."""

from __future__ import annotations

import hashlib
import posixpath
import shutil
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..models import AudiobookChapter, Book


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


def chapter_reader_smil_bytes(chapter: AudiobookChapter) -> bytes | None:
    path = _resolved(chapter.reader_smil_file_path or chapter.smil_file_path)
    if path is None or not path.is_file():
        return None
    return reader_smil_bytes(path.read_bytes(), chapter.source_href or chapter.content_file_name or "")


def text_reader_path(book: Book) -> Path | None:
    explicit = _resolved(book.audiobook_text_file_path)
    if explicit and explicit.is_file():
        return explicit
    legacy = LIBRARY_PATH / "audiobooks" / str(book.id) / "working.epub"
    return legacy if legacy.is_file() else None


def stage_reader_text_rendition(book_id: int, content_version: int, source: Path) -> tuple[str, int, str]:
    """Atomically stage a versioned text rendition before its metadata commits."""
    target = LIBRARY_PATH / "audiobooks" / str(book_id) / "reader" / f"text-v{content_version}.epub"
    _atomic_copy(source, target)
    return _relative(target), target.stat().st_size, sha256_file(target)


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
    publication_root = LIBRARY_PATH / "audiobooks" / str(book_id) / "reader"
    text_target = publication_root / f"text-v{content_version}.epub"
    _atomic_copy(source_text, text_target)
    text_size = text_target.stat().st_size
    text_sha = sha256_file(text_target)

    ready_count = 0
    for chapter in chapters:
        source_audio = _resolved(chapter.audio_file_path)
        source_smil = _resolved(chapter.smil_file_path)
        if source_audio is None or source_smil is None or not source_audio.is_file() or not source_smil.is_file():
            chapter.generation_state = "pending"
            continue

        href = normalize_resource_href(chapter.source_href or chapter.content_file_name, chapter.chapter_number)
        key = chapter.stable_chapter_key or stable_chapter_key(href)
        chapter.stable_chapter_key = key
        chapter.source_href = href
        audio_sha = sha256_file(source_audio)
        smil_content = reader_smil_bytes(source_smil.read_bytes(), href)
        smil_sha = sha256_bytes(smil_content)
        changed = chapter.audio_sha256 != audio_sha or chapter.smil_sha256 != smil_sha
        revision = max(1, (chapter.audio_revision or 0) + int(changed))
        chapter_dir = publication_root / "chapters" / key
        audio_target = chapter_dir / f"audio-v{revision}.mp3"
        smil_target = chapter_dir / f"overlay-v{revision}.smil"
        if changed or not audio_target.is_file():
            _atomic_copy(source_audio, audio_target)
        if changed or not smil_target.is_file():
            _atomic_write(smil_content, smil_target)

        sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        chapter.audio_revision = revision
        chapter.reader_audio_file_path = _relative(audio_target)
        chapter.reader_smil_file_path = _relative(smil_target)
        chapter.audio_size_bytes = audio_target.stat().st_size
        chapter.audio_sha256 = audio_sha
        chapter.smil_size_bytes = len(smil_content)
        chapter.smil_sha256 = smil_sha
        chapter.duration_ms = sum(sentence.audio_duration_ms or 0 for sentence in sentences)
        chapter.generation_state = "ready"
        ready_count += 1

    book.audiobook_revision = (book.audiobook_revision or 0) + 1
    pending_content_version = max(
        book.audiobook_pending_content_version or 0,
        (book.content_version or content_version) if (book.content_version or content_version) > content_version else 0,
    )
    book.audiobook_source_content_version = content_version
    book.audiobook_text_content_version = content_version
    book.audiobook_pending_content_version = pending_content_version or None
    book.audiobook_publication_state = (
        "complete" if chapters and ready_count == len(chapters) and not pending_content_version else "partial"
    )
    book.audiobook_text_file_path = _relative(text_target)
    book.audiobook_text_size_bytes = text_size
    book.audiobook_text_sha256 = text_sha
    book.audiobook_publication_error = None
    await db.commit()
