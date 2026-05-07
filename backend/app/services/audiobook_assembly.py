"""Phase 5: MP3 concatenation, SMIL generation, and EPUB 3 Media Overlay packaging."""

from __future__ import annotations

import logging
from pathlib import Path
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


def _build_smil(chapter_num: int, sentences: list, audio_filename: str) -> str:
    """Generate EPUB 3 Media Overlay SMIL XML for a chapter."""
    root = ET.Element(
        "smil",
        {
            "xmlns": "http://www.w3.org/ns/SMIL",
            "xmlns:epub": "http://www.idpf.org/2007/ops",
            "version": "3.0",
        },
    )
    body = ET.SubElement(root, "body")
    seq = ET.SubElement(body, "seq", {"epub:textref": f"chapter{chapter_num:04d}.xhtml", "epub:type": "chapter"})

    cumulative_ms = 0
    for sentence in sentences:
        duration_ms = sentence.audio_duration_ms or 0
        par = ET.SubElement(seq, "par", {"id": f"par_{sentence.html_element_id}"})
        ET.SubElement(
            par,
            "text",
            {"src": f"chapter{chapter_num:04d}.xhtml#{sentence.html_element_id}"},
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
    from pydub import AudioSegment

    if not sentences:
        logger.warning("Chapter %s has no sentences with audio; skipping assembly.", chapter.id)
        return

    combined = AudioSegment.empty()
    for sentence in sentences:
        if not sentence.audio_file_path:
            logger.warning("Sentence %s missing audio; inserting silence.", sentence.id)
            duration_ms = sentence.audio_duration_ms or 500
            combined += AudioSegment.silent(duration=duration_ms)
            continue
        snippet_full = LIBRARY_PATH.parent / sentence.audio_file_path
        if not snippet_full.exists():
            logger.warning("Snippet file missing for sentence %s; inserting silence.", sentence.id)
            combined += AudioSegment.silent(duration=sentence.audio_duration_ms or 500)
            continue
        combined += AudioSegment.from_mp3(str(snippet_full))

    audio_filename = f"ch{chapter.chapter_number:04d}.mp3"
    audio_path = output_dir / audio_filename
    combined.export(str(audio_path), format="mp3")
    logger.info("Assembled chapter audio: %s (%d ms)", audio_path, len(combined))

    smil_xml = _build_smil(chapter.chapter_number, sentences, audio_filename)
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

    chapters = await crud.audiobook.get_chapters_needing_reassembly(db, book_id)
    if not chapters:
        logger.info("No chapters need reassembly for book %s.", book_id)
        await crud.audiobook.set_book_pipeline_status(db, book_id, "complete")
        return

    for chapter in chapters:
        sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        await _assemble_chapter(book_id, chapter, sentences, output_dir, db)

    # Repackage the EPUB with updated media-overlay references
    working_epub_path = output_dir / "working.epub"
    if not working_epub_path.exists():
        logger.warning("Working EPUB not found for book %s; skipping repackage.", book_id)
        await crud.audiobook.set_book_pipeline_status(db, book_id, "complete")
        return

    ebook = epub.read_epub(str(working_epub_path))

    all_chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    for chapter in all_chapters:
        if not chapter.smil_file_path:
            continue
        smil_full = LIBRARY_PATH.parent / chapter.smil_file_path
        if not smil_full.exists():
            continue
        smil_item = epub.EpubSMIL(
            uid=f"smil_ch{chapter.chapter_number:04d}",
            file_name=f"ch{chapter.chapter_number:04d}.smil",
            content=smil_full.read_bytes(),
        )
        ebook.add_item(smil_item)

        # Attach media-overlay to the matching spine item
        for item in ebook.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            if f"chapter{chapter.chapter_number:04d}" in item.get_name():
                item.media_overlay = smil_item.id
                break

    audiobook_epub_path = output_dir / "audiobook.epub"
    epub.write_epub(str(audiobook_epub_path), ebook)
    logger.info("Repackaged audiobook EPUB: %s", audiobook_epub_path)

    await crud.audiobook.set_book_pipeline_status(db, book_id, "complete")
    logger.info("Assembly complete for book %s.", book_id)


# ebooklib constant needed above
import ebooklib  # noqa: E402
