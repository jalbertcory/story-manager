"""Audiobook pipeline API endpoints."""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..database import get_db
from ..models import (
    AudiobookChapter,
    AudiobookCharacter,
    AudiobookSentence,
    Book,
    ImportedAudiobook,
    ImportedAudiobookCue,
    ImportedAudiobookTrack,
)
from ..services.audiobook_import import (
    IMPORT_EXTENSIONS,
    MAX_AUDIOBOOK_UPLOAD_BYTES,
    asin_from_names,
    display_name_from_filename,
    imported_audiobook_dir,
    libation_backup_groups,
    rematch_track,
    safe_import_filename,
    stream_upload_to_path,
)
from ..services.audiobook_reading import ReadingBlock, chapter_reading_blocks
from ..services.processing_queue import queue_processing_job
from ..services import audiobook_llm
from ..services.transcription_providers import (
    transcription_provider_name,
    transcription_service_health,
)
from ..services.endpoint_pool import configured_endpoints, primary_provider
from ..services.endpoint_metrics import endpoint_summaries
from ..services.metadata.scoring import normalize_text
from ..services.tts_providers import (
    TTSRequest,
    design_omnivoice_voice,
    get_omnivoice_voice_sample,
    synthesize_speech_routed,
    tts_provider_name,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class _LegacyQueueHook:
    """No-op compatibility hook for integrations that patched the old queues."""

    async def enqueue(self, _record_id: int) -> bool:
        return True

    async def enqueue_sentence_audio(self, _book_id: int, _sentence_id: int) -> bool:
        return True

    async def enqueue_preview(self, _book_id: int, _chapter_id: int) -> bool:
        return True

    def has_book_job(self, _book_id: int) -> bool:
        return False


_legacy_queue_hook = _LegacyQueueHook()


def get_audiobook_queue():
    return _legacy_queue_hook


def get_audiobook_import_queue():
    return _legacy_queue_hook


def get_audiobook_alignment_queue():
    return _legacy_queue_hook


async def _notify_legacy_queue(getter, method: str, *args) -> None:
    queue = getter()
    if queue is not _legacy_queue_hook:
        await getattr(queue, method)(*args)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AudiobookStatusResponse(BaseModel):
    pipeline_status: Optional[str]
    next_phase: str
    pause_requested: bool
    stop_after_phase: Optional[str]
    last_error: Optional[str]
    sentence_counts: dict[str, int]
    review_counts: dict[str, int]
    summary: Optional[str]
    progress_current: int
    progress_total: int
    progress_percent: Optional[float]
    progress_detail: Optional[str]
    pipeline_started_at: Optional[datetime]
    pipeline_updated_at: Optional[datetime]
    batch_limit: Optional[int]
    llm_requests: int
    llm_provider: str
    llm_model: Optional[str]
    tts_provider: str
    tts_model: Optional[str]


class CharacterResponse(BaseModel):
    id: int
    book_id: int
    series_character_id: Optional[int] = None
    shared_series_name: Optional[str] = None
    name: str
    description: Optional[str]
    voice_prompt: Optional[str]
    tts_voice_id: Optional[str]
    tts_voice_provider: Optional[str]
    is_narrator: bool
    aliases: Optional[list[str]] = None
    evidence: Optional[list[str]] = None
    sentence_count: int = 0
    average_confidence: Optional[float] = None

    model_config = {"from_attributes": True}


class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    voice_prompt: Optional[str] = None
    tts_voice_id: Optional[str] = None
    is_narrator: Optional[bool] = None


class CharacterVoiceDesign(BaseModel):
    voice_prompt: Optional[str] = None


class SentenceResponse(BaseModel):
    id: int
    chapter_id: int
    character_id: Optional[int]
    html_element_id: str
    sequence_order: int
    original_text: str
    tagged_text: Optional[str]
    audio_file_path: Optional[str]
    audio_duration_ms: Optional[int]
    speaker_confidence: Optional[float]
    speaker_reason: Optional[str]
    status: str
    reading_block_index: Optional[int] = None
    reading_block_type: Optional[str] = None

    model_config = {"from_attributes": True}


class SentenceUpdate(BaseModel):
    character_id: Optional[int] = None
    tagged_text: Optional[str] = None


class ChapterResponse(BaseModel):
    id: int
    book_id: int
    chapter_number: int
    title: Optional[str]
    content_file_name: Optional[str]
    smil_file_path: Optional[str]
    audio_file_path: Optional[str]
    needs_reassembly: bool
    summary: Optional[str]
    summary_updated_at: Optional[datetime]
    preview_status: Optional[str]
    preview_error: Optional[str]
    sentence_count: int = 0
    processed_sentence_count: int = 0
    audio_generated_count: int = 0
    low_confidence_count: int = 0

    model_config = {"from_attributes": True}


class EndpointResponse(BaseModel):
    id: str
    name: str
    provider: str
    api_key_set: bool = False
    base_url: Optional[str] = None
    model: Optional[str] = None
    default_voice: Optional[str] = None
    language: Optional[str] = None


class SettingsResponse(BaseModel):
    id: Optional[int]
    llm_provider: Optional[str]
    llm_api_key_set: bool
    llm_base_url: Optional[str]
    llm_model: Optional[str]
    tts_provider: Optional[str]
    tts_api_key_set: bool
    tts_base_url: Optional[str]
    tts_model: Optional[str]
    tts_default_voice: Optional[str]
    transcription_provider: str
    transcription_api_key_set: bool
    transcription_base_url: Optional[str]
    transcription_model: Optional[str]
    transcription_language: Optional[str]
    llm_endpoints: list[EndpointResponse]
    tts_endpoints: list[EndpointResponse]
    transcription_endpoints: list[EndpointResponse]
    roster_prompt_template: Optional[str]
    diarization_prompt_template: Optional[str]


class EndpointUpdate(BaseModel):
    id: str
    name: str
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    default_voice: Optional[str] = None
    language: Optional[str] = None


class EndpointSpeedBuckets(BaseModel):
    under_5s: int
    from_5s_to_15s: int
    from_15s_to_60s: int
    over_60s: int


class EndpointStats(BaseModel):
    endpoint_id: str
    name: str
    provider: str
    model: Optional[str]
    requests: int
    answered: int
    failed: int
    success_rate: Optional[float]
    average_ms: Optional[float]
    p50_ms: Optional[float]
    p95_ms: Optional[float]
    fastest_ms: Optional[float]
    slowest_ms: Optional[float]
    answered_24h: int
    average_24h_ms: Optional[float]
    speed_buckets: EndpointSpeedBuckets
    last_answered_at: Optional[datetime]


class EndpointStatsResponse(BaseModel):
    endpoints: list[EndpointStats]


class AllEndpointStatsResponse(BaseModel):
    llm: list[EndpointStats]
    tts: list[EndpointStats]
    transcription: list[EndpointStats]


class SettingsUpdate(BaseModel):
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    tts_provider: Optional[str] = None
    tts_api_key: Optional[str] = None
    tts_base_url: Optional[str] = None
    tts_model: Optional[str] = None
    tts_default_voice: Optional[str] = None
    transcription_provider: Optional[str] = None
    transcription_api_key: Optional[str] = None
    transcription_base_url: Optional[str] = None
    transcription_model: Optional[str] = None
    transcription_language: Optional[str] = None
    llm_endpoints: Optional[list[EndpointUpdate]] = Field(default=None, min_length=1)
    tts_endpoints: Optional[list[EndpointUpdate]] = Field(default=None, min_length=1)
    transcription_endpoints: Optional[list[EndpointUpdate]] = Field(default=None, min_length=1)
    roster_prompt_template: Optional[str] = None
    diarization_prompt_template: Optional[str] = None


class SentenceListResponse(BaseModel):
    items: list[SentenceResponse]
    total: int
    page: int
    limit: int


def _reading_block_fields(
    reading_blocks: dict[str, ReadingBlock],
    html_element_id: str,
) -> dict[str, int | str | None]:
    block = reading_blocks.get(html_element_id)
    return {
        "reading_block_index": block.index if block else None,
        "reading_block_type": block.kind if block else None,
    }


class ImportedCueResponse(BaseModel):
    sentence_id: int
    html_element_id: str
    text: str
    clip_begin_ms: int
    clip_end_ms: int
    confidence: Optional[float]
    method: str
    reading_block_index: Optional[int] = None
    reading_block_type: Optional[str] = None


class ImportedTrackResponse(BaseModel):
    id: int
    sequence_order: int
    title: str
    matched_chapter_id: Optional[int]
    matched_chapter_title: Optional[str]
    source_start_ms: int
    source_end_ms: int
    duration_ms: int
    media_type: str
    cue_count: int
    alignment_score: Optional[float]
    audio_url: str
    cues_url: str
    smil_url: str


class ImportedAudiobookResponse(BaseModel):
    id: int
    book_id: int
    name: str
    source_type: str
    asin: Optional[str]
    status: str
    alignment_method: Optional[str]
    original_filenames: list[str]
    duration_ms: Optional[int]
    audio_size_bytes: int
    progress_current: int
    progress_total: int
    progress_detail: Optional[str]
    error: Optional[str]
    alignment_error: Optional[str]
    created_at: datetime
    is_reader_default: bool = False
    tracks: list[ImportedTrackResponse]


class ImportedTrackMatchUpdate(BaseModel):
    chapter_id: Optional[int] = None


class LibationBackupPreviewRequest(BaseModel):
    source_paths: list[str] = Field(min_length=1, max_length=50_000)


class LibationBackupMatchResponse(BaseModel):
    source_key: str
    folder_name: str
    source_title: str
    product_id: str
    file_count: int
    status: str
    match_method: Optional[str] = None
    book_id: Optional[int] = None
    book_title: Optional[str] = None
    book_author: Optional[str] = None
    existing_edition_id: Optional[int] = None
    detail: Optional[str] = None


class LibationBackupPreviewResponse(BaseModel):
    groups: list[LibationBackupMatchResponse]
    matched_count: int
    unmatched_count: int
    ambiguous_count: int
    already_imported_count: int
    ignored_file_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_book_or_404(book_id: int, db: AsyncSession) -> Book:
    book = await db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


async def _get_audiobook_book_or_404(book_id: int, db: AsyncSession) -> Book:
    book = await _get_book_or_404(book_id, db)
    if not book.audiobook_enabled:
        raise HTTPException(status_code=403, detail="Audiobook pipeline is not enabled for this book")
    return book


def _resolve_path(relative_path: Optional[str]) -> Optional[Path]:
    if not relative_path:
        return None
    path = (LIBRARY_PATH.parent / relative_path).resolve()
    return path if path.is_relative_to(LIBRARY_PATH.resolve()) else None


def _canonical_audio_track_ids(tracks: list[ImportedAudiobookTrack]) -> dict[str, int]:
    canonical_ids: dict[str, int] = {}
    for track in tracks:
        canonical_ids.setdefault(track.audio_file_path, track.id)
    return canonical_ids


async def _canonical_audio_track_id(track: ImportedAudiobookTrack, db: AsyncSession) -> int:
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


async def _imported_audiobook_response(
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
    canonical_audio_track_ids = _canonical_audio_track_ids(tracks)
    audio_paths = {path for track in tracks if (path := _resolve_path(track.audio_file_path)) is not None and path.is_file()}
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
                smil_url=f"/api/imported-audiobooks/{edition.id}/tracks/{track.id}/smil",
            )
            for track in tracks
        ],
    )


async def _get_imported_track_or_404(
    edition_id: int,
    track_id: int,
    db: AsyncSession,
) -> tuple[ImportedAudiobook, ImportedAudiobookTrack]:
    edition = await db.get(ImportedAudiobook, edition_id)
    track = await db.get(ImportedAudiobookTrack, track_id)
    if edition is None or track is None or track.imported_audiobook_id != edition.id:
        raise HTTPException(status_code=404, detail="Imported audiobook track not found")
    await _get_book_or_404(edition.book_id, db)
    return edition, track


def _normalized_identifier(value: Any) -> str:
    return re.sub(r"[^0-9a-z]", "", str(value).casefold())


def _book_identifier_values(book: Book) -> set[str]:
    values: set[str] = set()
    for value in (book.metadata_remote_ids or {}).values():
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if isinstance(candidate, (str, int)) and (normalized := _normalized_identifier(candidate)):
                values.add(normalized)
    return values


def _single_book_match(candidates: list[Book]) -> tuple[Book | None, bool]:
    unique = {book.id: book for book in candidates}
    if len(unique) == 1:
        return next(iter(unique.values())), False
    return None, len(unique) > 1


# ---------------------------------------------------------------------------
# Human-narrated audiobook imports
# ---------------------------------------------------------------------------


@router.post(
    "/api/audiobook/libation-backup/preview",
    response_model=LibationBackupPreviewResponse,
)
async def preview_libation_backup(
    request: LibationBackupPreviewRequest,
    db: AsyncSession = Depends(get_db),
) -> LibationBackupPreviewResponse:
    """Match a path-only Libation backup manifest before any audio is uploaded."""
    groups, ignored_file_count = libation_backup_groups(request.source_paths)
    books = list((await db.execute(select(Book).order_by(Book.title, Book.id))).scalars().all())
    imports = list((await db.execute(select(ImportedAudiobook))).scalars().all())
    imports_by_book_and_id = {
        (edition.book_id, _normalized_identifier(edition.asin)): edition for edition in imports if edition.asin
    }
    books_by_identifier: dict[str, list[Book]] = {}
    books_by_title: dict[str, list[Book]] = {}
    for book in books:
        for identifier in _book_identifier_values(book):
            books_by_identifier.setdefault(identifier, []).append(book)
        books_by_title.setdefault(normalize_text(book.title or ""), []).append(book)

    matches: list[LibationBackupMatchResponse] = []
    for group in groups:
        normalized_id = _normalized_identifier(group.product_id)
        identifier_candidates = books_by_identifier.get(normalized_id, [])
        matched_book, ambiguous = _single_book_match(identifier_candidates)
        match_method = "identifier" if matched_book else None
        if not identifier_candidates:
            title_candidates = books_by_title.get(normalize_text(group.title), [])
            matched_book, ambiguous = _single_book_match(title_candidates)
            match_method = "title" if matched_book else None

        if ambiguous:
            matches.append(
                LibationBackupMatchResponse(
                    source_key=group.source_key,
                    folder_name=group.folder_name,
                    source_title=group.title,
                    product_id=group.product_id,
                    file_count=len(group.source_paths),
                    status="ambiguous",
                    detail="More than one library book has this identifier or title.",
                )
            )
            continue
        if matched_book is None:
            matches.append(
                LibationBackupMatchResponse(
                    source_key=group.source_key,
                    folder_name=group.folder_name,
                    source_title=group.title,
                    product_id=group.product_id,
                    file_count=len(group.source_paths),
                    status="unmatched",
                    detail="No library book has the same identifier or title.",
                )
            )
            continue

        existing = imports_by_book_and_id.get((matched_book.id, normalized_id))
        status = "already_imported" if existing else "matched"
        matches.append(
            LibationBackupMatchResponse(
                source_key=group.source_key,
                folder_name=group.folder_name,
                source_title=group.title,
                product_id=group.product_id,
                file_count=len(group.source_paths),
                status=status,
                match_method=match_method,
                book_id=matched_book.id,
                book_title=matched_book.title,
                book_author=matched_book.author,
                existing_edition_id=existing.id if existing else None,
                detail=(f"Already attached as {existing.name} ({existing.status})." if existing else None),
            )
        )

    return LibationBackupPreviewResponse(
        groups=matches,
        matched_count=sum(match.status == "matched" for match in matches),
        unmatched_count=sum(match.status == "unmatched" for match in matches),
        ambiguous_count=sum(match.status == "ambiguous" for match in matches),
        already_imported_count=sum(match.status == "already_imported" for match in matches),
        ignored_file_count=ignored_file_count,
    )


@router.get(
    "/api/books/{book_id}/audiobook/imports",
    response_model=list[ImportedAudiobookResponse],
)
async def list_imported_audiobooks(
    book_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[ImportedAudiobookResponse]:
    await _get_book_or_404(book_id, db)
    result = await db.execute(
        select(ImportedAudiobook)
        .where(ImportedAudiobook.book_id == book_id)
        .order_by(ImportedAudiobook.created_at.desc(), ImportedAudiobook.id.desc())
    )
    editions = list(result.scalars().all())
    reader_default_id = next((edition.id for edition in editions if edition.status == "ready"), None)
    return [
        await _imported_audiobook_response(
            edition,
            db,
            is_reader_default=edition.id == reader_default_id,
        )
        for edition in editions
    ]


@router.post(
    "/api/books/{book_id}/audiobook/imports",
    response_model=ImportedAudiobookResponse,
)
async def upload_imported_audiobook(
    book_id: int,
    files: list[UploadFile] = File(...),
    name: Optional[str] = Form(None),
    source_paths: list[str] = Form(default=[]),
    auto_align: bool = Form(default=True),
    db: AsyncSession = Depends(get_db),
) -> ImportedAudiobookResponse:
    await _get_book_or_404(book_id, db)
    filenames = [file.filename or "" for file in files]
    display_names = source_paths if len(source_paths) == len(files) else filenames
    if not files or any(Path(filename).suffix.lower() not in IMPORT_EXTENSIONS for filename in filenames):
        supported = ", ".join(sorted(IMPORT_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"Upload audiobook audio, CUE, or ZIP files ({supported}).")
    edition = ImportedAudiobook(
        book_id=book_id,
        name=(name or "").strip() or display_name_from_filename(display_names[0]),
        asin=asin_from_names(display_names),
        status="queued",
        original_filenames=display_names,
        progress_detail="Receiving upload",
    )
    db.add(edition)
    await db.commit()
    await db.refresh(edition)
    edition_dir = imported_audiobook_dir(book_id, edition.id)
    incoming_dir = edition_dir / "incoming"
    remaining = MAX_AUDIOBOOK_UPLOAD_BYTES
    try:
        for upload in files:
            destination = incoming_dir / safe_import_filename(upload.filename or "audiobook")
            if destination.exists():
                destination = incoming_dir / f"{destination.stem}-{len(list(incoming_dir.glob('*'))) + 1}{destination.suffix}"
            written = await stream_upload_to_path(upload, destination, remaining)
            remaining -= written
        edition.progress_detail = "Queued for import"
        await db.commit()
        await queue_processing_job(
            db=db,
            job_type="import_audiobook",
            book_id=book_id,
            target_type="imported_audiobook",
            target_id=edition.id,
            payload={"auto_align": auto_align},
            dedupe_key=f"import_audiobook:imported_audiobook:{edition.id}",
            progress_detail="Queued after audiobook upload",
        )
        await _notify_legacy_queue(get_audiobook_import_queue, "enqueue", edition.id)
    except Exception as exc:
        edition.status = "error"
        edition.error = str(exc)
        edition.progress_detail = "Upload failed"
        await db.commit()
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return await _imported_audiobook_response(edition, db)


@router.post(
    "/api/imported-audiobooks/{edition_id}/retry",
    response_model=ImportedAudiobookResponse,
)
async def retry_imported_audiobook(
    edition_id: int,
    db: AsyncSession = Depends(get_db),
) -> ImportedAudiobookResponse:
    edition = await db.get(ImportedAudiobook, edition_id)
    if edition is None:
        raise HTTPException(status_code=404, detail="Imported audiobook not found")
    await _get_book_or_404(edition.book_id, db)
    if edition.status not in ("error", "queued"):
        raise HTTPException(status_code=409, detail=f"Audiobook import is {edition.status}, not retryable")
    edition.status = "queued"
    edition.error = None
    edition.progress_detail = "Queued for retry"
    await db.commit()
    await queue_processing_job(
        db=db,
        job_type="import_audiobook",
        book_id=edition.book_id,
        target_type="imported_audiobook",
        target_id=edition.id,
        dedupe_key=f"import_audiobook:imported_audiobook:{edition.id}",
        progress_detail="Queued audiobook import retry",
    )
    await _notify_legacy_queue(get_audiobook_import_queue, "enqueue", edition.id)
    return await _imported_audiobook_response(edition, db)


@router.post(
    "/api/imported-audiobooks/{edition_id}/align",
    response_model=ImportedAudiobookResponse,
)
async def align_imported_audiobook(
    edition_id: int,
    db: AsyncSession = Depends(get_db),
) -> ImportedAudiobookResponse:
    edition = await db.get(ImportedAudiobook, edition_id)
    if edition is None:
        raise HTTPException(status_code=404, detail="Imported audiobook not found")
    await _get_book_or_404(edition.book_id, db)
    if edition.status == "aligning":
        return await _imported_audiobook_response(edition, db)
    if edition.status != "ready":
        raise HTTPException(status_code=409, detail=f"Audiobook is {edition.status}, not ready for alignment")
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None or transcription_provider_name(settings) == "none":
        raise HTTPException(status_code=409, detail="Configure a transcription provider in Audio Settings first.")
    matched_count = await db.scalar(
        select(func.count(ImportedAudiobookTrack.id)).where(
            ImportedAudiobookTrack.imported_audiobook_id == edition.id,
            ImportedAudiobookTrack.matched_chapter_id.is_not(None),
        )
    )
    if not matched_count:
        raise HTTPException(status_code=409, detail="Match at least one audio track to a book chapter first.")
    edition.status = "aligning"
    edition.alignment_error = None
    edition.progress_current = 0
    edition.progress_total = matched_count
    edition.progress_detail = "Queued for timestamp alignment"
    await db.commit()
    await queue_processing_job(
        db=db,
        job_type="align_imported_audiobook",
        book_id=edition.book_id,
        target_type="imported_audiobook",
        target_id=edition.id,
        target_content_version=edition.matched_content_version,
        dedupe_key=f"align_imported_audiobook:imported_audiobook:{edition.id}",
        progress_detail="Queued timestamp alignment",
    )
    await _notify_legacy_queue(get_audiobook_alignment_queue, "enqueue", edition.id)
    return await _imported_audiobook_response(edition, db)


@router.post(
    "/api/imported-audiobooks/{edition_id}/rematch",
    response_model=ImportedAudiobookResponse,
)
async def rematch_imported_audiobook(
    edition_id: int,
    db: AsyncSession = Depends(get_db),
) -> ImportedAudiobookResponse:
    """Rebuild human-audio chapter matches and text cues without reimporting audio."""
    edition = await db.get(ImportedAudiobook, edition_id)
    if edition is None:
        raise HTTPException(status_code=404, detail="Imported audiobook not found")
    book = await _get_book_or_404(edition.book_id, db)
    if edition.status in ("queued", "importing", "aligning", "stale"):
        raise HTTPException(status_code=409, detail=f"Audiobook is already {edition.status}")
    track_count = await db.scalar(
        select(func.count(ImportedAudiobookTrack.id)).where(
            ImportedAudiobookTrack.imported_audiobook_id == edition.id,
        )
    )
    if not track_count:
        raise HTTPException(status_code=409, detail="This audiobook has no imported audio tracks")

    realign = edition.alignment_method in {"transcribed", "hybrid"}
    edition.status = "stale"
    edition.alignment_error = None
    edition.progress_current = 0
    edition.progress_total = track_count
    edition.progress_detail = "Chapter rematch queued"
    await db.commit()
    await queue_processing_job(
        db=db,
        job_type="rematch_imported_audiobook",
        book_id=book.id,
        target_type="imported_audiobook",
        target_id=edition.id,
        target_content_version=book.content_version,
        payload={"realign": realign},
        dedupe_key=f"rematch_imported_audiobook:imported_audiobook:{edition.id}:v{book.content_version or 1}",
        progress_detail="Queued to restore human-audio chapter matches and text cues",
    )
    return await _imported_audiobook_response(edition, db)


@router.delete("/api/imported-audiobooks/{edition_id}", status_code=204)
async def delete_imported_audiobook(
    edition_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    edition = await db.get(ImportedAudiobook, edition_id)
    if edition is None:
        raise HTTPException(status_code=404, detail="Imported audiobook not found")
    await _get_book_or_404(edition.book_id, db)
    edition_dir = imported_audiobook_dir(edition.book_id, edition.id)
    await db.delete(edition)
    await db.commit()
    shutil.rmtree(edition_dir, ignore_errors=True)
    return Response(status_code=204)


@router.get(
    "/api/imported-audiobooks/{edition_id}/tracks/{track_id}/cues",
    response_model=list[ImportedCueResponse],
)
async def get_imported_track_cues(
    edition_id: int,
    track_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[ImportedCueResponse]:
    edition, track = await _get_imported_track_or_404(edition_id, track_id, db)
    reading_blocks: dict[str, ReadingBlock] = {}
    if track.matched_chapter_id is not None:
        chapter = await db.get(AudiobookChapter, track.matched_chapter_id)
        # Imported narration is independent of the opt-in AI generation
        # pipeline. Human-only books still need their synchronized text cues.
        book = await _get_book_or_404(edition.book_id, db)
        if chapter is not None:
            reading_blocks = chapter_reading_blocks(book, chapter)
    result = await db.execute(
        select(ImportedAudiobookCue, AudiobookSentence)
        .join(AudiobookSentence, AudiobookSentence.id == ImportedAudiobookCue.sentence_id)
        .where(ImportedAudiobookCue.track_id == track.id)
        .order_by(ImportedAudiobookCue.sequence_order)
    )
    return [
        ImportedCueResponse(
            sentence_id=sentence.id,
            html_element_id=sentence.html_element_id,
            text=sentence.original_text,
            clip_begin_ms=cue.clip_begin_ms,
            clip_end_ms=cue.clip_end_ms,
            confidence=cue.confidence,
            method=cue.method,
            **_reading_block_fields(reading_blocks, sentence.html_element_id),
        )
        for cue, sentence in result.all()
    ]


@router.put(
    "/api/imported-audiobooks/{edition_id}/tracks/{track_id}/match",
    response_model=ImportedTrackResponse,
)
async def match_imported_track(
    edition_id: int,
    track_id: int,
    body: ImportedTrackMatchUpdate,
    db: AsyncSession = Depends(get_db),
) -> ImportedTrackResponse:
    edition, track = await _get_imported_track_or_404(edition_id, track_id, db)
    try:
        await rematch_track(track, body.chapter_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    refreshed = await _imported_audiobook_response(edition, db)
    return next(item for item in refreshed.tracks if item.id == track.id)


@router.get("/api/imported-audiobooks/{edition_id}/tracks/{track_id}/audio")
async def get_imported_track_audio(
    edition_id: int,
    track_id: int,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    _edition, track = await _get_imported_track_or_404(edition_id, track_id, db)
    full_path = _resolve_path(track.audio_file_path)
    if full_path is None or not full_path.exists():
        raise HTTPException(status_code=404, detail="Imported audiobook audio not found on disk")
    return FileResponse(str(full_path), media_type=track.media_type)


@router.get("/api/imported-audiobooks/{edition_id}/tracks/{track_id}/smil")
async def get_imported_track_smil(
    edition_id: int,
    track_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    edition, track = await _get_imported_track_or_404(edition_id, track_id, db)
    if track.matched_chapter_id is None:
        raise HTTPException(status_code=404, detail="Track is not matched to book text")
    chapter = await db.get(AudiobookChapter, track.matched_chapter_id)
    canonical_audio_track_id = await _canonical_audio_track_id(track, db)
    result = await db.execute(
        select(ImportedAudiobookCue, AudiobookSentence)
        .join(AudiobookSentence, AudiobookSentence.id == ImportedAudiobookCue.sentence_id)
        .where(ImportedAudiobookCue.track_id == track.id)
        .order_by(ImportedAudiobookCue.sequence_order)
    )
    root = ET.Element("smil", {"xmlns": "http://www.w3.org/ns/SMIL", "version": "3.0"})
    body = ET.SubElement(root, "body")
    seq = ET.SubElement(body, "seq")
    chapter_text_href = chapter.content_file_name.replace("\\", "/").rsplit("/", 1)[-1]
    for cue, sentence in result.all():
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
                "src": f"/api/imported-audiobooks/{edition.id}/tracks/{canonical_audio_track_id}/audio",
                "clipBegin": f"{cue.clip_begin_ms / 1000:.3f}s",
                "clipEnd": f"{cue.clip_end_ms / 1000:.3f}s",
            },
        )
    ET.indent(root, space="  ")
    payload = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
    return Response(payload, media_type="application/smil+xml")


# ---------------------------------------------------------------------------
# Pipeline control
# ---------------------------------------------------------------------------


@router.post("/api/books/{book_id}/audiobook/start")
async def start_pipeline(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    book = await _get_audiobook_book_or_404(book_id, db)
    status = book.audiobook_pipeline_status

    if status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        # Already running; idempotent
        return {"status": status, "queued": False}

    if status == "error" and await crud.audiobook.has_sentence_status(db, book_id, "error"):
        await crud.audiobook.reset_error_sentences_for_book(db, book_id)

    resume_status = await crud.audiobook.infer_audiobook_resume_status(db, book_id)
    if resume_status == "complete":
        await crud.audiobook.configure_book_pipeline_run(db, book_id, status="complete", stop_after_phase=None)
        return {"status": "complete", "queued": False}

    await crud.audiobook.configure_book_pipeline_run(db, book_id, status=resume_status, stop_after_phase=None)

    await queue_processing_job(
        db=db,
        job_type="audiobook_pipeline",
        book_id=book_id,
        target_type="book",
        target_id=book_id,
        target_content_version=book.content_version,
        payload={"mode": "resume"},
        dedupe_key=f"audiobook_pipeline:book:{book_id}:manual",
        progress_detail="Queued to run audiobook to completion",
    )
    await _notify_legacy_queue(get_audiobook_queue, "enqueue", book_id)
    current_status = (await db.get(Book, book_id)).audiobook_pipeline_status
    return {"status": current_status, "queued": True}


@router.post("/api/books/{book_id}/audiobook/step")
async def step_pipeline(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Run exactly the next recoverable phase, then stop for review."""
    book = await _get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        return {"status": book.audiobook_pipeline_status, "queued": False}

    if book.audiobook_pipeline_status == "error" and await crud.audiobook.has_sentence_status(db, book_id, "error"):
        await crud.audiobook.reset_error_sentences_for_book(db, book_id)

    next_phase = await crud.audiobook.infer_audiobook_resume_status(db, book_id)
    if next_phase == "complete":
        await crud.audiobook.configure_book_pipeline_run(db, book_id, status="complete", stop_after_phase=None)
        return {"status": "complete", "queued": False}

    await crud.audiobook.configure_book_pipeline_run(db, book_id, status=next_phase, stop_after_phase=next_phase)
    await queue_processing_job(
        db=db,
        job_type="audiobook_pipeline",
        book_id=book_id,
        target_type="book",
        target_id=book_id,
        target_content_version=book.content_version,
        payload={"mode": "resume"},
        dedupe_key=f"audiobook_pipeline:book:{book_id}:manual",
        progress_detail=f"Queued next audiobook stage: {next_phase}",
    )
    await _notify_legacy_queue(get_audiobook_queue, "enqueue", book_id)
    return {"status": next_phase, "queued": True, "stop_after_phase": next_phase}


@router.post("/api/books/{book_id}/audiobook/run-batch")
async def run_pipeline_batch(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Run one durable LLM/TTS/assembly work unit, then pause for review."""
    book = await _get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        return {"status": book.audiobook_pipeline_status, "queued": False}
    next_phase = await crud.audiobook.infer_audiobook_resume_status(db, book_id)
    if next_phase not in ("diarizing", "audio_gen", "assembling"):
        raise HTTPException(status_code=409, detail=f"{next_phase} is atomic; use Run Next Stage instead")
    await crud.audiobook.configure_book_pipeline_run(
        db,
        book_id,
        status=next_phase,
        stop_after_phase=None,
        batch_limit=1,
    )
    await queue_processing_job(
        db=db,
        job_type="audiobook_pipeline",
        book_id=book_id,
        target_type="book",
        target_id=book_id,
        target_content_version=book.content_version,
        payload={"mode": "resume"},
        dedupe_key=f"audiobook_pipeline:book:{book_id}:manual",
        progress_detail=f"Queued one audiobook batch: {next_phase}",
    )
    await _notify_legacy_queue(get_audiobook_queue, "enqueue", book_id)
    return {"status": next_phase, "queued": True, "batch_limit": 1}


@router.post("/api/books/{book_id}/audiobook/pause")
async def pause_pipeline(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    book = await _get_audiobook_book_or_404(book_id, db)
    active = book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling")
    await crud.audiobook.request_book_pipeline_pause(db, book_id)
    if active:
        return {"status": book.audiobook_pipeline_status, "pause_requested": True}
    await crud.audiobook.pause_book_pipeline_if_requested(db, book_id)
    return {"status": "paused", "pause_requested": False}


@router.post("/api/books/{book_id}/audiobook/rebuild")
async def rebuild_pipeline(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    book = await _get_audiobook_book_or_404(book_id, db)
    legacy_queue = get_audiobook_queue()
    if book.audiobook_pipeline_status in (
        "ingesting",
        "roster_gen",
        "diarizing",
        "audio_gen",
        "assembling",
    ) or (legacy_queue is not _legacy_queue_hook and legacy_queue.has_book_job(book_id)):
        raise HTTPException(status_code=409, detail="Pause the active pipeline before rebuilding it")
    await queue_processing_job(
        db=db,
        job_type="audiobook_pipeline",
        book_id=book_id,
        target_type="book",
        target_id=book_id,
        target_content_version=book.content_version,
        payload={"mode": "rebuild"},
        dedupe_key=f"audiobook_pipeline:book:{book_id}:rebuild",
        progress_detail="Queued AI audiobook rebuild; human editions preserved",
    )
    return {"status": book.audiobook_pipeline_status, "queued": True}


@router.post("/api/books/{book_id}/audiobook/audio/rebuild")
async def rebuild_audio_only(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Regenerate AI TTS and assembly without changing speaker analysis."""
    book = await _get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        raise HTTPException(status_code=409, detail="Pause the active pipeline before regenerating AI audio")
    chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    characters = await crud.audiobook.get_characters_for_book(db, book_id)
    review = await crud.audiobook.count_sentence_review_flags(db, book_id)
    if not chapters or not characters:
        raise HTTPException(status_code=409, detail="Run AI speaker analysis before regenerating TTS audio")
    if review.get("unassigned", 0):
        raise HTTPException(status_code=409, detail="Assign every sentence before regenerating TTS audio")

    await crud.audiobook.reset_audio_generation_for_book(db, book_id)
    await crud.audiobook.configure_book_pipeline_run(
        db,
        book_id,
        status="audio_gen",
        stop_after_phase=None,
    )
    await queue_processing_job(
        db=db,
        job_type="audiobook_pipeline",
        book_id=book_id,
        target_type="book",
        target_id=book_id,
        target_content_version=book.content_version,
        payload={"mode": "audio"},
        dedupe_key=f"audiobook_pipeline:book:{book_id}:audio-rebuild",
        progress_detail="Queued AI TTS regeneration; speakers and human editions preserved",
    )
    await _notify_legacy_queue(get_audiobook_queue, "enqueue", book_id)
    return {"status": "audio_gen", "queued": True}


@router.post("/api/books/{book_id}/audiobook/roster/rebuild")
async def rebuild_character_roster(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Re-run roster and diarization analysis without parsing the EPUB again."""
    book = await _get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        raise HTTPException(status_code=409, detail="Pause the active pipeline before regenerating the roster")
    chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    if not chapters:
        raise HTTPException(status_code=409, detail="Run ingestion before regenerating the roster")
    await crud.audiobook.reset_roster_and_diarization_for_book(db, book_id)
    await crud.audiobook.set_book_audiobook_summary(db, book_id, None)
    await crud.audiobook.configure_book_pipeline_run(
        db,
        book_id,
        status="roster_gen",
        stop_after_phase="roster_gen",
    )
    await queue_processing_job(
        db=db,
        job_type="audiobook_pipeline",
        book_id=book_id,
        target_type="book",
        target_id=book_id,
        target_content_version=book.content_version,
        payload={"mode": "roster"},
        dedupe_key=f"audiobook_pipeline:book:{book_id}:roster",
        progress_detail="Queued character-roster regeneration",
    )
    await _notify_legacy_queue(get_audiobook_queue, "enqueue", book_id)
    return {
        "status": "roster_gen",
        "queued": True,
        "stop_after_phase": "roster_gen",
    }


@router.get("/api/books/{book_id}/audiobook/status", response_model=AudiobookStatusResponse)
async def get_pipeline_status(book_id: int, db: AsyncSession = Depends(get_db)) -> AudiobookStatusResponse:
    book = await _get_audiobook_book_or_404(book_id, db)
    counts = await crud.audiobook.count_sentences_by_status(db, book_id)
    review_counts = await crud.audiobook.count_sentence_review_flags(db, book_id)
    next_phase = await crud.audiobook.infer_audiobook_resume_status(db, book_id)
    settings = await crud.audiobook.get_audiobook_settings(db)
    await db.refresh(book)
    total = book.audiobook_progress_total or 0
    percent = round((book.audiobook_progress_current or 0) * 100 / total, 1) if total else None
    return AudiobookStatusResponse(
        pipeline_status=book.audiobook_pipeline_status,
        next_phase=next_phase,
        pause_requested=book.audiobook_pause_requested,
        stop_after_phase=book.audiobook_stop_after_phase,
        last_error=book.audiobook_last_error,
        sentence_counts=counts,
        review_counts=review_counts,
        summary=book.audiobook_summary,
        progress_current=book.audiobook_progress_current or 0,
        progress_total=total,
        progress_percent=percent,
        progress_detail=book.audiobook_progress_detail,
        pipeline_started_at=book.audiobook_pipeline_started_at,
        pipeline_updated_at=book.audiobook_pipeline_updated_at,
        batch_limit=book.audiobook_batch_limit,
        llm_requests=book.audiobook_llm_requests or 0,
        llm_provider=(settings.llm_provider or "stub") if settings else "stub",
        llm_model=settings.llm_model if settings else None,
        tts_provider=tts_provider_name(settings),
        tts_model=settings.tts_model if settings else None,
    )


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------


@router.get("/api/books/{book_id}/audiobook/characters", response_model=list[CharacterResponse])
async def list_characters(book_id: int, db: AsyncSession = Depends(get_db)) -> list[CharacterResponse]:
    book = await _get_audiobook_book_or_404(book_id, db)
    chars = await crud.audiobook.get_characters_for_book(db, book_id)
    stats = await crud.audiobook.get_character_sentence_stats(db, book_id)
    return [
        CharacterResponse(
            id=character.id,
            book_id=character.book_id,
            series_character_id=character.series_character_id,
            shared_series_name=book.series if character.series_character_id else None,
            name=character.name,
            description=character.description,
            voice_prompt=character.voice_prompt,
            tts_voice_id=character.tts_voice_id,
            tts_voice_provider=character.tts_voice_provider,
            is_narrator=character.is_narrator,
            aliases=character.aliases or [],
            evidence=character.evidence or [],
            sentence_count=stats.get(character.id, {}).get("sentence_count", 0),
            average_confidence=stats.get(character.id, {}).get("average_confidence"),
        )
        for character in chars
    ]


@router.put("/api/audiobook/characters/{char_id}", response_model=CharacterResponse)
async def update_character(char_id: int, body: CharacterUpdate, db: AsyncSession = Depends(get_db)) -> CharacterResponse:
    data = body.model_dump(exclude_unset=True)
    voice_changed = bool({"voice_prompt", "tts_voice_id"} & data.keys())

    existing = await crud.audiobook.get_character(db, char_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Character not found")
    await _get_audiobook_book_or_404(existing.book_id, db)
    if (
        "voice_prompt" in data
        and data["voice_prompt"] != existing.voice_prompt
        and existing.tts_voice_provider == "omnivoice"
        and "tts_voice_id" not in data
    ):
        # The saved reference represents the old design. A new one will be
        # auditioned manually or provisioned automatically on next use.
        data["tts_voice_id"] = None
        data["tts_voice_provider"] = None
    if "tts_voice_id" in data:
        voice_id = data["tts_voice_id"]
        if isinstance(voice_id, str):
            voice_id = voice_id.strip() or None
        data["tts_voice_id"] = voice_id
        settings = await crud.audiobook.get_audiobook_settings(db)
        data["tts_voice_provider"] = tts_provider_name(settings) if voice_id else None

    char = await crud.audiobook.update_character(db, char_id, data)
    linked_characters = await crud.audiobook.propagate_character_profile_across_series(db, char)

    if voice_changed:
        for linked_character in linked_characters:
            await crud.audiobook.cascade_voice_change(db, linked_character.id)

    return CharacterResponse.model_validate(char)


@router.post("/api/audiobook/characters/{char_id}/design-voice", response_model=CharacterResponse)
async def design_character_voice(
    char_id: int,
    body: CharacterVoiceDesign,
    db: AsyncSession = Depends(get_db),
) -> CharacterResponse:
    character = await crud.audiobook.get_character(db, char_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    await _get_audiobook_book_or_404(character.book_id, db)
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None or tts_provider_name(settings) != "omnivoice":
        raise HTTPException(status_code=409, detail="Select OmniVoice in Audio Settings first")

    requested_prompt = body.voice_prompt if "voice_prompt" in body.model_fields_set else character.voice_prompt
    voice_prompt = requested_prompt or "[gender-neutral][pitch-medium][speed-normal]"
    # Do not replace the saved profile/reference until a new design succeeds.
    designed = await design_omnivoice_voice(settings, voice_prompt)
    character.voice_prompt = voice_prompt
    character.tts_voice_id = designed.id
    character.tts_voice_provider = "omnivoice"
    await db.commit()
    linked_characters = await crud.audiobook.propagate_character_profile_across_series(db, character)
    for linked_character in linked_characters:
        await crud.audiobook.cascade_voice_change(db, linked_character.id)
    await db.refresh(character)
    return CharacterResponse.model_validate(character)


@router.get("/api/audiobook/characters/{char_id}/voice-sample")
async def get_character_voice_sample(
    char_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    character = await crud.audiobook.get_character(db, char_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    await _get_audiobook_book_or_404(character.book_id, db)
    if character.tts_voice_provider != "omnivoice" or not character.tts_voice_id:
        raise HTTPException(status_code=404, detail="Design a consistent OmniVoice voice first")
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None or tts_provider_name(settings) != "omnivoice":
        raise HTTPException(status_code=409, detail="Select OmniVoice in Audio Settings first")
    sample = await get_omnivoice_voice_sample(
        settings,
        character.tts_voice_id,
    )
    return Response(
        sample.audio_bytes,
        media_type=sample.media_type,
        # The character can be assigned a different provider voice later while
        # retaining the same sample URL, so do not let browsers keep a stale clip.
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/api/books/{book_id}/audiobook/roster/share-series")
async def share_character_roster_with_series(
    book_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    book = await _get_audiobook_book_or_404(book_id, db)
    if not book.series:
        raise HTTPException(status_code=409, detail="Assign this book to a series before sharing its roster")
    characters = await crud.audiobook.get_characters_for_book(db, book_id)
    if not characters:
        raise HTTPException(status_code=409, detail="Generate a character roster before sharing it")
    linked = await crud.audiobook.sync_book_roster_with_series(
        db,
        book,
        characters,
        prefer_series=True,
    )
    affected_book_ids: set[int] = {book_id}
    for character in characters:
        siblings = await crud.audiobook.propagate_character_profile_across_series(db, character)
        affected_book_ids.update(sibling.book_id for sibling in siblings)
    return {
        "series": book.series,
        "profiles": linked,
        "books_updated": len(affected_book_ids),
    }


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------


@router.get("/api/books/{book_id}/audiobook/sentences", response_model=SentenceListResponse)
async def list_sentences(
    book_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=1000),
    chapter_id: Optional[int] = Query(None),
    review_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> SentenceListResponse:
    book = await _get_audiobook_book_or_404(book_id, db)
    sentences, total = await crud.audiobook.get_sentences_paginated(
        db,
        book_id,
        page=page,
        limit=limit,
        chapter_id=chapter_id,
        review_only=review_only,
    )
    reading_blocks: dict[str, ReadingBlock] = {}
    if chapter_id is not None:
        chapter = await db.get(AudiobookChapter, chapter_id)
        if chapter is not None and chapter.book_id == book_id:
            reading_blocks = chapter_reading_blocks(book, chapter)
    items = []
    for sentence in sentences:
        response = SentenceResponse.model_validate(sentence)
        items.append(
            response.model_copy(
                update=_reading_block_fields(reading_blocks, sentence.html_element_id),
            )
        )
    return SentenceListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
    )


@router.put("/api/audiobook/sentences/{sentence_id}", response_model=SentenceResponse)
async def update_sentence(sentence_id: int, body: SentenceUpdate, db: AsyncSession = Depends(get_db)) -> SentenceResponse:
    existing = await db.get(AudiobookSentence, sentence_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Sentence not found")
    chapter = await db.get(AudiobookChapter, existing.chapter_id)
    if chapter:
        await _get_audiobook_book_or_404(chapter.book_id, db)
    if body.character_id is not None:
        character = await db.get(AudiobookCharacter, body.character_id)
        if chapter is None or character is None or character.book_id != chapter.book_id:
            raise HTTPException(status_code=404, detail="Character not found for this book")

    sentence = await crud.audiobook.update_sentence_speaker(
        db,
        sentence_id=sentence_id,
        character_id=body.character_id,
        tagged_text=body.tagged_text or "",
    )

    return SentenceResponse.model_validate(sentence)


@router.post("/api/books/{book_id}/audiobook/sentences/{sentence_id}/generate-audio")
async def generate_sentence_audio(
    book_id: int,
    sentence_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    book = await _get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        raise HTTPException(status_code=409, detail="Pause the full-book pipeline before generating sentence audio")
    sentence = await db.get(AudiobookSentence, sentence_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="Audiobook sentence not found")
    chapter = await db.get(AudiobookChapter, sentence.chapter_id)
    if chapter is None or chapter.book_id != book_id:
        raise HTTPException(status_code=404, detail="Audiobook sentence not found")
    if sentence.status in ("audio_queued", "audio_generating"):
        return {"status": sentence.status, "queued": False, "sentence_id": sentence_id}
    if sentence.status not in ("ready_for_audio", "error"):
        raise HTTPException(status_code=409, detail=f"Sentence is {sentence.status}, not ready for audio")
    if sentence.character_id is None:
        raise HTTPException(status_code=409, detail="Assign a speaker before generating sentence audio")

    await crud.audiobook.set_sentence_status(db, sentence_id, "audio_queued")
    await queue_processing_job(
        db=db,
        job_type="generate_sentence_audio",
        book_id=book_id,
        target_type="audiobook_sentence",
        target_id=sentence_id,
        target_content_version=book.content_version,
        dedupe_key=f"generate_sentence_audio:audiobook_sentence:{sentence_id}",
        progress_detail="Queued sentence-audio generation",
    )
    await _notify_legacy_queue(get_audiobook_queue, "enqueue_sentence_audio", book_id, sentence_id)
    return {
        "status": "audio_queued",
        "queued": True,
        "sentence_id": sentence_id,
    }


@router.get("/api/audiobook/sentences/{sentence_id}/audio")
async def get_sentence_audio(sentence_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    sentence = await db.get(AudiobookSentence, sentence_id)
    if sentence is None or not sentence.audio_file_path:
        raise HTTPException(status_code=404, detail="Audio not available")
    chapter = await db.get(AudiobookChapter, sentence.chapter_id)
    if chapter:
        await _get_audiobook_book_or_404(chapter.book_id, db)
    full_path = _resolve_path(sentence.audio_file_path)
    if not full_path or not full_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")
    return FileResponse(str(full_path), media_type="audio/mpeg")


# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------


@router.get("/api/books/{book_id}/audiobook/chapters", response_model=list[ChapterResponse])
async def list_chapters(book_id: int, db: AsyncSession = Depends(get_db)) -> list[ChapterResponse]:
    await _get_book_or_404(book_id, db)
    chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    response = []
    for chapter in chapters:
        sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        processed = [sentence for sentence in sentences if sentence.status != "pending_diarization"]
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
                sentence_count=len(sentences),
                processed_sentence_count=len(processed),
                audio_generated_count=sum(1 for sentence in sentences if sentence.status == "audio_generated"),
                low_confidence_count=sum(
                    1
                    for sentence in sentences
                    if sentence.speaker_confidence is not None and sentence.speaker_confidence < 0.65
                ),
            )
        )
    return response


@router.post("/api/books/{book_id}/audiobook/chapters/{chapter_id}/preview-audio")
async def generate_chapter_preview(
    book_id: int,
    chapter_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    book = await _get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        raise HTTPException(status_code=409, detail="Pause the full-book pipeline before generating a preview")
    chapter = await db.get(AudiobookChapter, chapter_id)
    if chapter is None or chapter.book_id != book_id:
        raise HTTPException(status_code=404, detail="Audiobook chapter not found")
    sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter_id)
    pending = sum(1 for sentence in sentences if sentence.status == "pending_diarization")
    if not sentences or pending:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Finish speaker analysis for this chapter first ({pending} sentences remain)"
                if pending
                else "Chapter has no narratable sentences"
            ),
        )
    if chapter.preview_status in ("queued", "generating"):
        return {"status": chapter.preview_status, "queued": False}
    await crud.audiobook.set_chapter_preview_status(db, chapter_id, "queued")
    await queue_processing_job(
        db=db,
        job_type="generate_chapter_preview",
        book_id=book_id,
        target_type="audiobook_chapter",
        target_id=chapter_id,
        target_content_version=book.content_version,
        dedupe_key=f"generate_chapter_preview:audiobook_chapter:{chapter_id}",
        progress_detail="Queued chapter-preview generation",
    )
    await _notify_legacy_queue(get_audiobook_queue, "enqueue_preview", book_id, chapter_id)
    return {"status": "queued", "queued": True, "chapter_id": chapter_id}


@router.get("/api/books/{book_id}/audiobook/chapters/{chapter_id}/audio")
async def get_chapter_audio(book_id: int, chapter_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    chapter = await db.get(AudiobookChapter, chapter_id)
    if chapter is None or chapter.book_id != book_id or not chapter.audio_file_path:
        raise HTTPException(status_code=404, detail="Audio not available")
    await _get_audiobook_book_or_404(book_id, db)
    full_path = _resolve_path(chapter.audio_file_path)
    if not full_path or not full_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")
    return FileResponse(str(full_path), media_type="audio/mpeg")


@router.get("/api/books/{book_id}/audiobook/download")
async def download_audiobook(book_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    book = await _get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status != "complete":
        raise HTTPException(status_code=409, detail="Audiobook generation is not complete")
    full_path = (LIBRARY_PATH / "audiobooks" / str(book_id) / "audiobook.epub").resolve()
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Audiobook EPUB not found on disk")
    filename = f"{book.title or 'audiobook'}-audiobook.epub"
    return FileResponse(str(full_path), media_type="application/epub+zip", filename=filename)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _default_endpoint(capability: str) -> dict[str, Any]:
    return {
        "id": f"default-{capability}",
        "name": "Primary",
        "provider": {"llm": "stub", "tts": "stub", "transcription": "none"}[capability],
    }


def _public_endpoints(settings, capability: str) -> list[EndpointResponse]:
    endpoints = configured_endpoints(settings, capability) if settings is not None else [_default_endpoint(capability)]
    return [
        EndpointResponse(
            id=str(endpoint.get("id") or f"{capability}-{index + 1}"),
            name=str(endpoint.get("name") or f"Endpoint {index + 1}"),
            provider=str(endpoint.get("provider") or _default_endpoint(capability)["provider"]),
            api_key_set=bool(endpoint.get("api_key")),
            base_url=endpoint.get("base_url"),
            model=endpoint.get("model"),
            default_voice=endpoint.get("default_voice"),
            language=endpoint.get("language"),
        )
        for index, endpoint in enumerate(endpoints)
    ]


def _settings_response(settings) -> SettingsResponse:
    if settings is None:
        return SettingsResponse(
            id=None,
            llm_provider="stub",
            llm_api_key_set=False,
            llm_base_url=None,
            llm_model=None,
            tts_provider="stub",
            tts_api_key_set=False,
            tts_base_url=None,
            tts_model=None,
            tts_default_voice=None,
            transcription_provider="none",
            transcription_api_key_set=False,
            transcription_base_url=None,
            transcription_model=None,
            transcription_language=None,
            llm_endpoints=_public_endpoints(None, "llm"),
            tts_endpoints=_public_endpoints(None, "tts"),
            transcription_endpoints=_public_endpoints(None, "transcription"),
            roster_prompt_template=None,
            diarization_prompt_template=None,
        )
    return SettingsResponse(
        id=settings.id,
        llm_provider=settings.llm_provider,
        llm_api_key_set=bool(settings.llm_api_key),
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_model,
        tts_provider=settings.tts_provider or "stub",
        tts_api_key_set=bool(settings.tts_api_key),
        tts_base_url=settings.tts_base_url,
        tts_model=settings.tts_model,
        tts_default_voice=settings.tts_default_voice,
        transcription_provider=settings.transcription_provider or "none",
        transcription_api_key_set=bool(settings.transcription_api_key),
        transcription_base_url=settings.transcription_base_url,
        transcription_model=settings.transcription_model,
        transcription_language=settings.transcription_language,
        llm_endpoints=_public_endpoints(settings, "llm"),
        tts_endpoints=_public_endpoints(settings, "tts"),
        transcription_endpoints=_public_endpoints(settings, "transcription"),
        roster_prompt_template=settings.roster_prompt_template,
        diarization_prompt_template=settings.diarization_prompt_template,
    )


def _merge_endpoint_secrets(
    incoming: list[dict[str, Any]],
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_by_id = {str(endpoint.get("id")): endpoint for endpoint in existing}
    merged = []
    for index, endpoint in enumerate(incoming):
        endpoint = dict(endpoint)
        endpoint_id = str(endpoint.get("id") or f"endpoint-{index + 1}")
        previous = existing_by_id.get(endpoint_id, {})
        if "api_key" not in endpoint:
            if previous.get("provider") == endpoint.get("provider"):
                endpoint["api_key"] = previous.get("api_key")
        elif not endpoint["api_key"]:
            endpoint["api_key"] = None
        endpoint["id"] = endpoint_id
        endpoint["name"] = str(endpoint.get("name") or f"Endpoint {index + 1}").strip()
        endpoint["provider"] = str(endpoint.get("provider") or "").strip().lower()
        merged.append(endpoint)
    return merged


def _sync_primary_columns(data: dict[str, Any], capability: str, endpoints: list[dict[str, Any]]) -> None:
    primary = endpoints[0]
    prefix = "transcription" if capability == "transcription" else capability
    for endpoint_field, column_field in (
        ("provider", f"{prefix}_provider"),
        ("api_key", f"{prefix}_api_key"),
        ("base_url", f"{prefix}_base_url"),
        ("model", f"{prefix}_model"),
    ):
        data[column_field] = primary.get(endpoint_field)
    if capability == "tts":
        data["tts_default_voice"] = primary.get("default_voice")
    elif capability == "transcription":
        data["transcription_language"] = primary.get("language")


def _tts_signature(endpoints: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (
            endpoint.get("provider"),
            endpoint.get("base_url"),
            endpoint.get("model"),
            endpoint.get("default_voice"),
        )
        for endpoint in endpoints
    ]


@router.get("/api/audiobook/settings", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)) -> SettingsResponse:
    settings = await crud.audiobook.get_audiobook_settings(db)
    return _settings_response(settings)


@router.put("/api/audiobook/settings", response_model=SettingsResponse)
async def update_settings(body: SettingsUpdate, db: AsyncSession = Depends(get_db)) -> SettingsResponse:
    data = body.model_dump(exclude_unset=True)
    previous = await crud.audiobook.get_audiobook_settings(db)
    previous_tts_endpoints = configured_endpoints(previous, "tts") if previous else []

    for capability in ("llm", "tts", "transcription"):
        field = f"{capability}_endpoints"
        if field not in data:
            continue
        existing = configured_endpoints(previous, capability) if previous else []
        endpoints = _merge_endpoint_secrets(data[field], existing)
        data[field] = endpoints
        _sync_primary_columns(data, capability, endpoints)

    previous_provider = tts_provider_name(previous)
    next_provider = str(data.get("tts_provider") or previous_provider).strip().lower()
    if "tts_endpoints" not in data and next_provider != previous_provider and "tts_api_key" not in data:
        data["tts_api_key"] = None
    previous_transcription_provider = transcription_provider_name(previous)
    next_transcription_provider = str(data.get("transcription_provider") or previous_transcription_provider).strip().lower()
    if (
        "transcription_endpoints" not in data
        and next_transcription_provider != previous_transcription_provider
        and "transcription_api_key" not in data
    ):
        data["transcription_api_key"] = None

    previous_tts = {
        "tts_provider": previous_provider,
        "tts_base_url": previous.tts_base_url if previous else None,
        "tts_model": previous.tts_model if previous else None,
        "tts_default_voice": previous.tts_default_voice if previous else None,
    }
    next_tts = {name: data.get(name, value) for name, value in previous_tts.items()}
    next_tts["tts_provider"] = next_provider
    if "tts_endpoints" in data:
        tts_changed = _tts_signature(previous_tts_endpoints) != _tts_signature(data["tts_endpoints"])
    else:
        tts_changed = next_tts != previous_tts
    settings = await crud.audiobook.upsert_audiobook_settings(db, data)
    if tts_changed:
        await crud.audiobook.invalidate_generated_audio_for_tts_change(db)
    return _settings_response(settings)


@router.get("/api/audiobook/settings/llm-stats", response_model=EndpointStatsResponse)
async def get_llm_endpoint_stats(db: AsyncSession = Depends(get_db)) -> EndpointStatsResponse:
    """Compare reliability and response latency across configured LLM endpoints."""
    settings = await crud.audiobook.get_audiobook_settings(db)
    return EndpointStatsResponse(endpoints=await endpoint_summaries(db, settings, "llm"))


@router.get("/api/audiobook/settings/endpoint-stats", response_model=AllEndpointStatsResponse)
async def get_endpoint_stats(db: AsyncSession = Depends(get_db)) -> AllEndpointStatsResponse:
    """Compare reliability and response latency across all configured AI endpoints."""
    settings = await crud.audiobook.get_audiobook_settings(db)
    return AllEndpointStatsResponse(
        llm=await endpoint_summaries(db, settings, "llm"),
        tts=await endpoint_summaries(db, settings, "tts"),
        transcription=await endpoint_summaries(db, settings, "transcription"),
    )


@router.post("/api/audiobook/settings/test-llm")
async def test_llm_settings(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None or primary_provider(settings, "llm", "stub") == "stub":
        return {"status": "ready", "provider": "stub", "model": None, "response": "local harness"}
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }
    routed = await audiobook_llm._call_llm_routed(
        settings,
        [{"role": "user", "content": "Return JSON with status set to ready."}],
        response_schema=schema,
    )
    raw = routed.value
    parsed = audiobook_llm._extract_json(raw)
    return {
        "status": parsed.get("status", "unknown") if isinstance(parsed, dict) else "unknown",
        "endpoint": routed.endpoint.get("name"),
        "provider": routed.endpoint.get("provider"),
        "model": routed.endpoint.get("model"),
        "response": parsed,
    }


@router.post("/api/audiobook/settings/test-tts")
async def test_tts_settings(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None:
        return {"status": "ready", "provider": "stub", "model": None, "audio_bytes": 0}
    routed = await synthesize_speech_routed(
        settings,
        TTSRequest(
            text="Story Manager text to speech is ready.",
        ),
    )
    audio = routed.value
    if not audio:
        raise HTTPException(status_code=502, detail="The TTS provider returned an empty response.")
    return {
        "status": "ready",
        "endpoint": routed.endpoint.get("name"),
        "provider": routed.endpoint.get("provider"),
        "model": routed.endpoint.get("model"),
        "audio_bytes": len(audio),
    }


@router.post("/api/audiobook/settings/test-transcription")
async def test_transcription_settings(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None:
        raise HTTPException(status_code=409, detail="Configure a transcription provider first.")
    try:
        payload = await transcription_service_health(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "status": payload.get("status"),
        "endpoint": payload.get("endpoint", {}).get("name"),
        "provider": payload.get("endpoint", {}).get("provider"),
        "model": payload.get("model"),
        "device": payload.get("device"),
    }
