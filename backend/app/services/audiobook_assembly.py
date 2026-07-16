"""Phase 5: MP3 concatenation, SMIL generation, and EPUB 3 Media Overlay packaging."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import shutil
import tempfile
from xml.etree import ElementTree as ET

from ebooklib import epub
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH

logger = logging.getLogger(__name__)


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
            "libmp3lame",
            "-b:a",
            "64k",
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
    chapters = await crud.audiobook.get_chapters_pending_assembly(db, book_id)
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

    all_chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
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

        # Attach media-overlay to the matching spine item
        for item in ebook.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            if item.get_name() == chapter.content_file_name:
                item.media_overlay = smil_item.id
                break

    temporary_epub_path = output_dir / "audiobook.tmp.epub"
    temporary_epub_path.unlink(missing_ok=True)
    _ensure_toc_link_ids(ebook.toc)
    epub.write_epub(str(temporary_epub_path), ebook)
    temporary_epub_path.replace(audiobook_epub_path)
    logger.info("Repackaged audiobook EPUB: %s", audiobook_epub_path)

    if not await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
        await crud.audiobook.set_book_pipeline_status(db, book_id, "complete")
    logger.info("Assembly complete for book %s.", book_id)


# ebooklib constant needed above
import ebooklib  # noqa: E402
