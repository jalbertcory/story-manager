"""Phase 5: MP3 concatenation, SMIL generation, and EPUB 3 Media Overlay packaging."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import shutil
import tempfile
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
from ebooklib import epub
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import AUDIOBOOK_ASSEMBLY_MARKER, LIBRARY_PATH
from ..models import AudiobookChapter
from .audiobook_publication import publish_reader_audiobook

logger = logging.getLogger(__name__)

_DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
_OPF_NAMESPACE = "http://www.idpf.org/2007/opf"
_CALIBRE_NAMESPACE = "http://calibre.kovidgoyal.net/2009/metadata"


def _relative_path(full_path: Path) -> str:
    return str(full_path.relative_to(LIBRARY_PATH.parent))


def _ms_to_clock(ms: int) -> str:
    """Convert milliseconds to SMIL clock value hh:mm:ss.mmm."""
    total_s, millis = divmod(ms, 1000)
    total_m, secs = divmod(total_s, 60)
    hours, mins = divmod(total_m, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d}.{millis:03d}"


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


def _sanitize_epub3_metadata(ebook) -> None:
    """Remove EPUB 2-only metadata syntax that is invalid in an EPUB 3 package."""
    ebook.metadata.pop(_CALIBRE_NAMESPACE, None)
    for entries in ebook.metadata.get(_DC_NAMESPACE, {}).values():
        for _, attributes in entries:
            if not attributes:
                continue
            for name in list(attributes):
                if name.startswith(f"{{{_OPF_NAMESPACE}}}"):
                    del attributes[name]


def _document_ids(ebook) -> dict[str, set[str]]:
    ids_by_name: dict[str, set[str]] = {}
    for item in ebook.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.content, "html.parser")
        ids_by_name[item.get_name()] = {str(node.get("id")) for node in soup.find_all(attrs={"id": True})}
    return ids_by_name


def _sanitize_toc_targets(toc_items, ids_by_name: dict[str, set[str]]) -> None:
    """Strip only fragments that do not exist in their target XHTML document."""
    for item in toc_items or []:
        target = item[0] if isinstance(item, (tuple, list)) and item else item
        if isinstance(target, (epub.Link, epub.Section)) and "#" in target.href:
            file_name, fragment = target.href.split("#", 1)
            if file_name in ids_by_name and fragment not in ids_by_name[file_name]:
                target.href = file_name
        if isinstance(item, (tuple, list)) and len(item) > 1:
            _sanitize_toc_targets(item[1], ids_by_name)


def _prepare_epub3_documents(ebook) -> None:
    """Supply required document titles and declare embedded SVG content."""
    fallback_title = ebook.title or "Audiobook"
    for item in ebook.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        if isinstance(item, epub.EpubNav):
            continue
        soup = BeautifulSoup(item.content, "html.parser")
        if not item.title:
            heading = soup.find(["h1", "h2", "h3"])
            item.title = heading.get_text(" ", strip=True) if heading else fallback_title
        if soup.find("svg") is not None and "svg" not in item.properties:
            item.properties.append("svg")


def _ensure_epub3_navigation(ebook) -> None:
    if not any(isinstance(item, epub.EpubNav) for item in ebook.get_items()):
        ebook.add_item(epub.EpubNav(uid="nav", file_name="nav.xhtml", title="Navigation"))


def _build_smil(chapter, sentences: list, audio_filename: str) -> str:
    """Generate EPUB 3 Media Overlay SMIL XML for a chapter."""
    text_file_name = chapter.content_file_name or f"chapter{chapter.chapter_number:04d}.xhtml"
    root = ET.Element(
        "smil",
        {
            "xmlns": "http://www.w3.org/ns/SMIL",
            "xmlns:epub": "http://www.idpf.org/2007/ops",
            "version": "3.0",
        },
    )
    body = ET.SubElement(root, "body")
    seq = ET.SubElement(body, "seq", {"epub:textref": text_file_name, "epub:type": "chapter"})

    cumulative_ms = 0
    for sentence in sentences:
        duration_ms = sentence.audio_duration_ms or 0
        par = ET.SubElement(seq, "par", {"id": f"par_{sentence.html_element_id}"})
        ET.SubElement(
            par,
            "text",
            {"src": f"{text_file_name}#{sentence.html_element_id}"},
        )
        ET.SubElement(
            par,
            "audio",
            {
                "src": audio_filename,
                "clipBegin": _ms_to_clock(cumulative_ms),
                "clipEnd": _ms_to_clock(cumulative_ms + duration_ms),
            },
        )
        cumulative_ms += duration_ms

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


async def _assemble_chapter(book_id: int, chapter, sentences: list, output_dir: Path, db: AsyncSession) -> None:
    if not sentences:
        logger.warning("Chapter %s has no sentences with audio; skipping assembly.", chapter.id)
        return

    snippet_paths: list[Path] = []
    for sentence in sentences:
        if not sentence.audio_file_path:
            raise RuntimeError(f"Sentence {sentence.id} is missing audio path during assembly.")
        snippet_full = LIBRARY_PATH.parent / sentence.audio_file_path
        if not snippet_full.exists():
            raise RuntimeError(f"Snippet file missing for sentence {sentence.id}: {snippet_full}")
        snippet_paths.append(snippet_full)

    # Treat the MP3 artifacts as authoritative. Older pipeline versions trusted
    # provider-reported durations, which accumulated into visibly incorrect
    # SMIL timelines. Rounding cumulative frame durations preserves both every
    # intermediate boundary and the exact rounded chapter total.
    from mutagen.mp3 import MP3

    cumulative_exact_ms = 0.0
    previous_boundary_ms = 0
    corrected_durations = 0
    for sentence, snippet_path in zip(sentences, snippet_paths, strict=True):
        snippet = MP3(str(snippet_path))
        cumulative_exact_ms += snippet.info.length * 1000
        next_boundary_ms = round(cumulative_exact_ms)
        duration_ms = next_boundary_ms - previous_boundary_ms
        if sentence.audio_duration_ms != duration_ms:
            sentence.audio_duration_ms = duration_ms
            corrected_durations += 1
        previous_boundary_ms = next_boundary_ms
    if corrected_durations:
        await db.commit()
        logger.info(
            "Corrected %d legacy sentence duration(s) in chapter %s.",
            corrected_durations,
            chapter.id,
        )

    audio_filename = f"ch{chapter.chapter_number:04d}.mp3"
    audio_path = output_dir / audio_filename
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to assemble audiobook chapters.")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", dir=output_dir, encoding="utf-8") as manifest:
        for snippet_path in snippet_paths:
            escaped_path = str(snippet_path).replace("'", "'\\''")
            manifest.write(f"file '{escaped_path}'\n")
        manifest.flush()
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            manifest.name,
            "-codec:a",
            "copy",
            "-y",
            str(audio_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode:
            message = stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"ffmpeg chapter assembly failed: {message}")
    total_duration_ms = sum(sentence.audio_duration_ms or 0 for sentence in sentences)
    logger.info("Assembled chapter audio: %s (%d ms)", audio_path, total_duration_ms)

    smil_xml = _build_smil(chapter, sentences, audio_filename)
    smil_filename = f"ch{chapter.chapter_number:04d}.smil"
    smil_path = output_dir / smil_filename
    smil_path.write_text(smil_xml, encoding="utf-8")

    await crud.audiobook.update_chapter_assembly(
        db,
        chapter_id=chapter.id,
        audio_file_path=_relative_path(audio_path),
        smil_file_path=_relative_path(smil_path),
    )


async def assemble_chapter_preview(book_id: int, chapter_id: int, db: AsyncSession) -> None:
    """Assemble one chapter without requiring the rest of the book to be ready."""
    chapter = await db.get(AudiobookChapter, chapter_id)
    if chapter is None or chapter.book_id != book_id:
        raise RuntimeError("Audiobook chapter not found.")
    sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter_id)
    if not sentences or any(sentence.status != "audio_generated" for sentence in sentences):
        raise RuntimeError("Every sentence in the chapter needs audio before preview assembly.")
    output_dir = LIBRARY_PATH.parent / "library" / "audiobooks" / str(book_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    await crud.audiobook.invalidate_packaged_audiobook(db, book_id)
    await _assemble_chapter(book_id, chapter, sentences, output_dir, db)


async def assemble_book(book_id: int, db: AsyncSession) -> None:
    """Phase 5: assemble all chapters that need reassembly and repackage the EPUB."""
    output_dir = LIBRARY_PATH.parent / "library" / "audiobooks" / str(book_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    if await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
        logger.info("Book %s paused before assembly.", book_id)
        return

    if await crud.audiobook.has_sentence_status(db, book_id, "error"):
        await crud.audiobook.set_book_pipeline_status(db, book_id, "error")
        raise RuntimeError(f"Cannot assemble book {book_id}: sentence audio generation has errors.")

    if not await crud.audiobook.all_sentences_audio_generated(db, book_id):
        await crud.audiobook.set_book_pipeline_status(db, book_id, "error")
        raise RuntimeError(f"Cannot assemble book {book_id}: not all sentences have generated audio.")

    audiobook_epub_path = output_dir / "audiobook.epub"
    assembly_marker = output_dir / AUDIOBOOK_ASSEMBLY_MARKER
    if assembly_marker.is_file():
        chapters = await crud.audiobook.get_chapters_pending_assembly(db, book_id)
    else:
        # Existing outputs were assembled with timeline-shortening re-encoding.
        # Rebuild every chapter once with frame-copy concatenation.
        chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    if chapters:
        # Once chapter state changes, an older package is no longer a valid
        # completion marker. Removing it makes an interrupted package step
        # resume at assembly on the next run.
        audiobook_epub_path.unlink(missing_ok=True)
    else:
        logger.info("No chapters need reassembly for book %s; rebuilding the EPUB package.", book_id)

    await crud.audiobook.update_book_pipeline_progress(
        db, book_id, current=0, total=len(chapters), detail=f"Preparing {len(chapters)} chapter assemblies"
    )
    for chapter_index, chapter in enumerate(chapters, start=1):
        if await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
            logger.info("Book %s paused between chapter assemblies.", book_id)
            return
        sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        await _assemble_chapter(book_id, chapter, sentences, output_dir, db)
        await crud.audiobook.update_book_pipeline_progress(
            db,
            book_id,
            current=chapter_index,
            total=len(chapters),
            detail=f"Assembled chapter {chapter_index} of {len(chapters)}",
        )
        if await crud.audiobook.consume_book_batch_limit(db, book_id):
            logger.info("Book %s paused after one chapter assembly.", book_id)
            return

    # Repackage the EPUB with updated media-overlay references
    working_epub_path = output_dir / "working.epub"
    if not working_epub_path.exists():
        await crud.audiobook.set_book_pipeline_status(db, book_id, "error")
        raise RuntimeError(f"Working EPUB not found for book {book_id}; run ingestion again.")

    ebook = epub.read_epub(str(working_epub_path))
    _sanitize_epub3_metadata(ebook)
    _prepare_epub3_documents(ebook)
    _sanitize_toc_targets(ebook.toc, _document_ids(ebook))
    _ensure_epub3_navigation(ebook)

    all_chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    total_duration_ms = 0
    for chapter in all_chapters:
        if not chapter.smil_file_path:
            raise RuntimeError(f"Missing SMIL path for book {book_id}, chapter {chapter.id}.")
        smil_full = LIBRARY_PATH.parent / chapter.smil_file_path
        if not smil_full.exists():
            raise RuntimeError(f"Missing SMIL file for book {book_id}, chapter {chapter.id}.")
        audio_full = LIBRARY_PATH.parent / chapter.audio_file_path if chapter.audio_file_path else None
        if audio_full is None or not audio_full.exists():
            raise RuntimeError(f"Missing chapter audio for book {book_id}, chapter {chapter.id}.")

        audio_item = epub.EpubItem(
            uid=f"audio_ch{chapter.chapter_number:04d}",
            file_name=f"ch{chapter.chapter_number:04d}.mp3",
            media_type="audio/mpeg",
            content=audio_full.read_bytes(),
        )
        ebook.add_item(audio_item)

        smil_item = epub.EpubSMIL(
            uid=f"smil_ch{chapter.chapter_number:04d}",
            file_name=f"ch{chapter.chapter_number:04d}.smil",
            content=smil_full.read_bytes(),
        )
        ebook.add_item(smil_item)

        sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        chapter_duration_ms = sum(sentence.audio_duration_ms or 0 for sentence in sentences)
        total_duration_ms += chapter_duration_ms
        ebook.add_metadata(
            "OPF",
            "meta",
            _ms_to_clock(chapter_duration_ms),
            {"property": "media:duration", "refines": f"#{smil_item.id}"},
        )

        # Attach media-overlay to the matching spine item
        for item in ebook.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            if item.get_name() == chapter.content_file_name:
                item.media_overlay = smil_item.id
                break

    ebook.add_metadata(
        "OPF",
        "meta",
        _ms_to_clock(total_duration_ms),
        {"property": "media:duration"},
    )

    temporary_epub_path = output_dir / "audiobook.tmp.epub"
    temporary_epub_path.unlink(missing_ok=True)
    _ensure_toc_link_ids(ebook.toc)
    epub.write_epub(str(temporary_epub_path), ebook)
    temporary_epub_path.replace(audiobook_epub_path)
    assembly_marker.write_text("EPUB 3 media-overlay package with frame-copy audio\n", encoding="utf-8")
    await publish_reader_audiobook(db, book_id)
    logger.info("Repackaged audiobook EPUB: %s", audiobook_epub_path)

    if not await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
        await crud.audiobook.set_book_pipeline_status(db, book_id, "complete")
    logger.info("Assembly complete for book %s.", book_id)


# ebooklib constant needed above
import ebooklib  # noqa: E402
