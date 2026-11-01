"""Read models for audiobook editions, tracks and chapters."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..audiobook_schemas import (
    ChapterResponse,
    ImportedAudiobookResponse,
    ImportedTrackResponse,
)
from ..models import (
    AudiobookChapter,
    AudiobookSentence,
    Book,
    ImportedAudiobook,
    ImportedAudiobookCue,
    ImportedAudiobookTrack,
)
from .audiobook_import import (
    CURRENT_DERIVED_FORMAT_VERSION,
    CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION,
)
from .library_paths import resolve_library_file


class AudiobookViewNotFoundError(LookupError):
    """A requested book, edition, track or derived document does not exist."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def require_book(book_id: int, db: AsyncSession) -> Book:
    book = await db.get(Book, book_id)
    if book is None:
        raise AudiobookViewNotFoundError("Book not found")
    return book


async def find_imported_track(
    edition_id: int,
    track_id: int,
    db: AsyncSession,
) -> tuple[ImportedAudiobook, ImportedAudiobookTrack]:
    edition = await db.get(ImportedAudiobook, edition_id)
    track = await db.get(ImportedAudiobookTrack, track_id)
    if edition is None or track is None or track.imported_audiobook_id != edition.id:
        raise AudiobookViewNotFoundError("Imported audiobook track not found")
    await require_book(edition.book_id, db)
    return edition, track


def canonical_track_ids_by_audio_path(tracks: list[ImportedAudiobookTrack]) -> dict[str, int]:
    canonical_ids: dict[str, int] = {}
    for track in tracks:
        canonical_ids.setdefault(track.audio_file_path, track.id)
    return canonical_ids


async def find_canonical_audio_track_id(track: ImportedAudiobookTrack, db: AsyncSession) -> int:
    result = await db.execute(
        select(ImportedAudiobookTrack.id)
        .where(
            ImportedAudiobookTrack.imported_audiobook_id == track.imported_audiobook_id,
            ImportedAudiobookTrack.audio_file_path == track.audio_file_path,
        )
        .order_by(ImportedAudiobookTrack.sequence_order)
        .limit(1)
    )
    return result.scalar_one()


async def imported_audiobook_response(
    edition: ImportedAudiobook,
    db: AsyncSession,
    *,
    is_reader_default: bool = False,
) -> ImportedAudiobookResponse:
    result = await db.execute(
        select(ImportedAudiobookTrack)
        .where(ImportedAudiobookTrack.imported_audiobook_id == edition.id)
        .order_by(ImportedAudiobookTrack.sequence_order)
    )
    tracks = list(result.scalars().all())
    canonical_audio_track_ids = canonical_track_ids_by_audio_path(tracks)
    audio_paths = {
        path for track in tracks if (path := resolve_library_file(track.audio_file_path)) is not None and path.is_file()
    }
    chapter_ids = {track.matched_chapter_id for track in tracks if track.matched_chapter_id is not None}
    chapters = {}
    if chapter_ids:
        chapter_result = await db.execute(select(AudiobookChapter).where(AudiobookChapter.id.in_(chapter_ids)))
        chapters = {chapter.id: chapter for chapter in chapter_result.scalars().all()}
    cue_counts = {}
    if tracks:
        cue_result = await db.execute(
            select(ImportedAudiobookCue.track_id, func.count(ImportedAudiobookCue.id))
            .where(ImportedAudiobookCue.track_id.in_([track.id for track in tracks]))
            .group_by(ImportedAudiobookCue.track_id)
        )
        cue_counts = {track_id: count for track_id, count in cue_result.all()}
    needs_asset_upgrade = (
        not edition.source_manifest_sha256 or (edition.derived_format_version or 0) < CURRENT_DERIVED_FORMAT_VERSION
    )
    needs_rebuild = (
        needs_asset_upgrade
        or (edition.pipeline_version or 0) < CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION
        or bool(edition.alignment_error)
    )
    return ImportedAudiobookResponse(
        id=edition.id,
        book_id=edition.book_id,
        name=edition.name,
        source_type=edition.source_type,
        asin=edition.asin,
        status=edition.status,
        alignment_method=edition.alignment_method,
        original_filenames=edition.original_filenames or [],
        duration_ms=edition.duration_ms,
        audio_size_bytes=sum(path.stat().st_size for path in audio_paths),
        source_size_bytes=edition.source_size_bytes,
        source_manifest_sha256=edition.source_manifest_sha256,
        derived_revision=edition.derived_revision or 0,
        derived_format_version=edition.derived_format_version or 0,
        pipeline_version=edition.pipeline_version or 0,
        needs_upgrade=needs_asset_upgrade,
        needs_rebuild=needs_rebuild,
        progress_current=edition.progress_current or 0,
        progress_total=edition.progress_total or 0,
        progress_detail=edition.progress_detail,
        error=edition.error,
        alignment_error=edition.alignment_error,
        created_at=edition.created_at,
        is_reader_default=is_reader_default,
        tracks=[
            ImportedTrackResponse(
                id=track.id,
                sequence_order=track.sequence_order,
                title=track.title,
                matched_chapter_id=track.matched_chapter_id,
                matched_chapter_title=(
                    chapters[track.matched_chapter_id].title
                    if track.matched_chapter_id is not None and track.matched_chapter_id in chapters
                    else None
                ),
                match_method=track.match_method,
                source_start_ms=track.source_start_ms,
                source_end_ms=track.source_end_ms,
                duration_ms=track.duration_ms,
                media_type=track.media_type,
                cue_count=cue_counts.get(track.id, 0),
                alignment_score=track.alignment_score,
                audio_url=(
                    f"/api/imported-audiobooks/{edition.id}/tracks/"
                    f"{canonical_audio_track_ids[track.audio_file_path]}/audio"
                ),
                cues_url=f"/api/imported-audiobooks/{edition.id}/tracks/{track.id}/cues",
                smil_url=(
                    f"/api/imported-audiobooks/{edition.id}/tracks/{track.id}/smil"
                    if track.matched_chapter_id is not None
                    else None
                ),
            )
            for track in tracks
        ],
    )


async def list_imported_audiobook_responses(book_id: int, db: AsyncSession) -> list[ImportedAudiobookResponse]:
    """All editions of a book, newest first, flagging the newest ready one as the reader default."""
    await require_book(book_id, db)
    result = await db.execute(
        select(ImportedAudiobook)
        .where(ImportedAudiobook.book_id == book_id)
        .order_by(ImportedAudiobook.created_at.desc(), ImportedAudiobook.id.desc())
    )
    editions = list(result.scalars().all())
    reader_default_id = next((edition.id for edition in editions if edition.status == "ready"), None)
    return [
        await imported_audiobook_response(
            edition,
            db,
            is_reader_default=edition.id == reader_default_id,
        )
        for edition in editions
    ]


_NO_SENTENCES: crud.audiobook.ChapterSentenceCounts = {
    "sentence_count": 0,
    "processed_sentence_count": 0,
    "audio_generated_count": 0,
    "low_confidence_count": 0,
}


async def chapter_responses(book_id: int, db: AsyncSession) -> list[ChapterResponse]:
    await require_book(book_id, db)
    chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    counts = await crud.audiobook.get_sentence_counts_for_book(db, book_id)
    response = []
    for chapter in chapters:
        chapter_counts = counts.get(chapter.id, _NO_SENTENCES)
        response.append(
            ChapterResponse(
                id=chapter.id,
                book_id=chapter.book_id,
                chapter_number=chapter.chapter_number,
                title=chapter.title,
                content_file_name=chapter.content_file_name,
                smil_file_path=chapter.smil_file_path,
                audio_file_path=chapter.audio_file_path,
                needs_reassembly=chapter.needs_reassembly,
                summary=chapter.summary,
                summary_updated_at=chapter.summary_updated_at,
                preview_status=chapter.preview_status,
                preview_error=chapter.preview_error,
                sentence_count=chapter_counts["sentence_count"],
                processed_sentence_count=chapter_counts["processed_sentence_count"],
                audio_generated_count=chapter_counts["audio_generated_count"],
                low_confidence_count=chapter_counts["low_confidence_count"],
            )
        )
    return response


def imported_track_audio_path(track: ImportedAudiobookTrack) -> Path:
    full_path = resolve_library_file(track.audio_file_path)
    if full_path is None or not full_path.exists():
        raise AudiobookViewNotFoundError("Imported audiobook audio not found on disk")
    return full_path


async def imported_track_smil(
    edition: ImportedAudiobook,
    track: ImportedAudiobookTrack,
    db: AsyncSession,
    *,
    audio_url_prefix: str = "/api/imported-audiobooks",
) -> str:
    """Build the SMIL media overlay for one imported track.

    ``audio_url_prefix`` selects the admin or reader-key audio route the
    overlay points at.
    """
    if track.matched_chapter_id is None:
        raise AudiobookViewNotFoundError("Track is not matched to book text")
    primary_chapter = await db.get(AudiobookChapter, track.matched_chapter_id)
    if primary_chapter is None:
        raise AudiobookViewNotFoundError("Matched chapter no longer exists")
    canonical_audio_track_id = await find_canonical_audio_track_id(track, db)
    result = await db.execute(
        select(ImportedAudiobookCue, AudiobookSentence)
        .join(AudiobookSentence, AudiobookSentence.id == ImportedAudiobookCue.sentence_id)
        .where(ImportedAudiobookCue.track_id == track.id)
        .order_by(ImportedAudiobookCue.sequence_order)
    )
    rows = result.all()
    chapter_ids = {sentence.chapter_id for _cue, sentence in rows}
    chapter_result = await db.execute(select(AudiobookChapter).where(AudiobookChapter.id.in_(chapter_ids)))
    chapters = {chapter.id: chapter for chapter in chapter_result.scalars().all()}
    root = ET.Element("smil", {"xmlns": "http://www.w3.org/ns/SMIL", "version": "3.0"})
    body = ET.SubElement(root, "body")
    seq = ET.SubElement(body, "seq")
    for cue, sentence in rows:
        sentence_chapter = chapters.get(sentence.chapter_id, primary_chapter)
        if not sentence_chapter.content_file_name:
            raise AudiobookViewNotFoundError("Matched chapter has no EPUB content file")
        chapter_text_href = sentence_chapter.content_file_name.replace("\\", "/").rsplit("/", 1)[-1]
        par = ET.SubElement(seq, "par")
        ET.SubElement(
            par,
            "text",
            {"src": f"{chapter_text_href}#{sentence.html_element_id}"},
        )
        ET.SubElement(
            par,
            "audio",
            {
                "src": f"{audio_url_prefix}/{edition.id}/tracks/{canonical_audio_track_id}/audio",
                "clipBegin": f"{cue.clip_begin_ms / 1000:.3f}s",
                "clipEnd": f"{cue.clip_end_ms / 1000:.3f}s",
            },
        )
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
