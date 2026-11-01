"""Human-narrated audiobook import endpoints."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.exc import DataError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import api_schemas as contracts
from .. import crud
from ..audiobook_schemas import (
    HumanAudiobookRebuildPreview,
    ImportedAudiobookResponse,
    ImportedCueResponse,
    ImportedTrackMatchUpdate,
    ImportedTrackResponse,
    LibationBackupPreviewRequest,
    LibationBackupPreviewResponse,
    reading_block_fields,
)
from ..database import get_db
from ..job_payloads import (
    RebuildImportedAudiobookPayload,
    RematchImportedAudiobookPayload,
    UpgradeImportedAudiobookPayload,
)
from ..lifecycle import IMPORTED_AUDIOBOOK, AlignmentMethod, ImportedAudiobookStatus, transition_state
from ..models import (
    AudiobookChapter,
    AudiobookSentence,
    Book,
    ImportedAudiobook,
    ImportedAudiobookCue,
    ImportedAudiobookTrack,
    SourceType,
)
from ..services import audiobook_import, audiobook_views, libation_matching
from ..services.audiobook_import import (
    CURRENT_DERIVED_FORMAT_VERSION,
    CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION,
    IMPORT_EXTENSIONS,
    AudiobookUploadTooLargeError,
    rematch_track,
)
from ..services.audiobook_metadata import filename_metadata
from ..services.audiobook_reading import chapter_reading_blocks
from ..services.audiobook_uploads import receive_audiobook_upload
from ..services.audiobook_views import AudiobookViewNotFoundError, imported_audiobook_response
from ..services.processing_queue import queue_processing_job
from ..services.transcription_providers import (
    transcription_provider_name,
)
from .audiobook_common import get_book_or_404

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_imported_track_or_404(
    edition_id: int,
    track_id: int,
    db: AsyncSession,
) -> tuple[ImportedAudiobook, ImportedAudiobookTrack]:
    try:
        return await audiobook_views.find_imported_track(edition_id, track_id, db)
    except AudiobookViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc


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
    return await libation_matching.preview_libation_backup(request.source_paths, db)


@router.get(
    "/api/books/{book_id}/audiobook/imports",
    response_model=list[ImportedAudiobookResponse],
)
async def list_imported_audiobooks(
    book_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[ImportedAudiobookResponse]:
    try:
        return await audiobook_views.list_imported_audiobook_responses(book_id, db)
    except AudiobookViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc


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
    await get_book_or_404(book_id, db)
    filenames = [file.filename or "" for file in files]
    if not files or any(Path(filename).suffix.lower() not in IMPORT_EXTENSIONS for filename in filenames):
        supported = ", ".join(sorted(IMPORT_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"Upload audiobook audio, CUE, or ZIP files ({supported}).")
    try:
        edition = await receive_audiobook_upload(
            db,
            book_id=book_id,
            files=files,
            name=name,
            source_paths=source_paths,
            auto_align=auto_align,
        )
    except AudiobookUploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Audiobook upload failed: {exc}") from exc
    return await imported_audiobook_response(edition, db)


@router.post("/api/audiobooks/upload", response_model=ImportedAudiobookResponse)
async def upload_audio_only_book(
    files: list[UploadFile] = File(...),
    title: str = Form(default=""),
    author: str = Form(default="Unknown author"),
    name: Optional[str] = Form(None),
    source_paths: list[str] = Form(default=[]),
    infer_title: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
) -> ImportedAudiobookResponse:
    if not files or any(Path(file.filename or "").suffix.lower() not in IMPORT_EXTENSIONS for file in files):
        raise HTTPException(status_code=400, detail="Choose supported audiobook audio, CUE, or ZIP files")
    inferred = filename_metadata(source_paths or [file.filename or "" for file in files])
    book_title = title.strip() or inferred["title"]
    book = Book(
        title=book_title,
        author=author.strip() or "Unknown author",
        source_type=SourceType.audiobook,
        metadata_details={"audiobook_import": {"inferred_title": book_title if infer_title or not title.strip() else None}},
        metadata_remote_ids={"asin": inferred["asin"]} if inferred.get("asin") else None,
    )
    db.add(book)
    try:
        await db.commit()
    except DataError as exc:
        await db.rollback()
        if getattr(exc.orig, "sqlstate", None) == "22P02" and "enum sourcetype" in str(exc.orig):
            raise HTTPException(
                status_code=503,
                detail=(
                    "Audio-only imports require a database update. "
                    "Run make migrate on the Story Manager server, then retry the import."
                ),
            ) from exc
        raise
    await db.refresh(book)
    return await upload_imported_audiobook(book.id, files, name, source_paths, False, db)


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
    await get_book_or_404(edition.book_id, db)
    if edition.status not in ("error", "queued"):
        raise HTTPException(status_code=409, detail=f"Audiobook import is {edition.status}, not retryable")
    transition_state(
        edition,
        "status",
        IMPORTED_AUDIOBOOK,
        ImportedAudiobookStatus.QUEUED,
        context=f"imported audiobook {edition.id}",
    )
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
    return await imported_audiobook_response(edition, db)


@router.post(
    "/api/imported-audiobooks/{edition_id}/upgrade",
    response_model=ImportedAudiobookResponse,
)
async def upgrade_imported_audiobook(
    edition_id: int,
    db: AsyncSession = Depends(get_db),
) -> ImportedAudiobookResponse:
    """Rebuild derived chapter audio from the retained immutable source files."""
    edition = await db.get(ImportedAudiobook, edition_id)
    if edition is None:
        raise HTTPException(status_code=404, detail="Imported audiobook not found")
    await get_book_or_404(edition.book_id, db)
    if edition.status != ImportedAudiobookStatus.READY.value:
        raise HTTPException(status_code=409, detail=f"Audiobook import is {edition.status}, not ready to upgrade")
    edition.progress_current = 0
    edition.progress_total = 0
    edition.progress_detail = "Chapter-audio upgrade queued"
    await db.commit()
    await queue_processing_job(
        db=db,
        job_type="upgrade_imported_audiobook",
        book_id=edition.book_id,
        target_type="imported_audiobook",
        target_id=edition.id,
        payload=UpgradeImportedAudiobookPayload(format_version=CURRENT_DERIVED_FORMAT_VERSION),
        dedupe_key=f"upgrade_imported_audiobook:imported_audiobook:{edition.id}",
        progress_detail=f"Queued chapter-audio format v{CURRENT_DERIVED_FORMAT_VERSION}",
    )
    return await imported_audiobook_response(edition, db)


@router.post("/api/audiobook/imports/upgrade-all", response_model=contracts.QueuedImports)
async def upgrade_all_imported_audiobooks(db: AsyncSession = Depends(get_db)) -> contracts.QueuedImports:
    """Queue every ready human audiobook that has rebuildable legacy assets."""
    result = await db.execute(select(ImportedAudiobook).order_by(ImportedAudiobook.id))
    editions = list(result.scalars().all())
    queued = 0
    skipped = 0
    for edition in editions:
        needs_upgrade = (
            not edition.source_manifest_sha256 or (edition.derived_format_version or 0) < CURRENT_DERIVED_FORMAT_VERSION
        )
        if edition.status != ImportedAudiobookStatus.READY.value or not needs_upgrade:
            skipped += 1
            continue
        await queue_processing_job(
            db=db,
            job_type="upgrade_imported_audiobook",
            book_id=edition.book_id,
            target_type="imported_audiobook",
            target_id=edition.id,
            payload=UpgradeImportedAudiobookPayload(format_version=CURRENT_DERIVED_FORMAT_VERSION),
            dedupe_key=f"upgrade_imported_audiobook:imported_audiobook:{edition.id}",
            progress_detail=f"Queued chapter-audio format v{CURRENT_DERIVED_FORMAT_VERSION}",
        )
        edition.progress_detail = "Chapter-audio upgrade queued"
        queued += 1
    await db.commit()
    return {"queued_count": queued, "skipped_count": skipped}


def _needs_human_audiobook_rebuild(edition: ImportedAudiobook) -> bool:
    return bool(
        not edition.source_manifest_sha256
        or (edition.derived_format_version or 0) < CURRENT_DERIVED_FORMAT_VERSION
        or (edition.pipeline_version or 0) < CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION
        or edition.alignment_error
    )


async def _human_audiobook_rebuild_inventory(
    db: AsyncSession,
) -> tuple[list[ImportedAudiobook], dict[int, int]]:
    result = await db.execute(select(ImportedAudiobook).order_by(ImportedAudiobook.id))
    editions = list(result.scalars().all())
    track_result = await db.execute(
        select(
            ImportedAudiobookTrack.imported_audiobook_id,
            func.count(ImportedAudiobookTrack.id),
        ).group_by(ImportedAudiobookTrack.imported_audiobook_id)
    )
    return editions, {edition_id: count for edition_id, count in track_result.all()}


@router.get(
    "/api/audiobook/imports/rebuild-preview",
    response_model=HumanAudiobookRebuildPreview,
)
async def preview_human_audiobook_rebuilds(
    db: AsyncSession = Depends(get_db),
) -> HumanAudiobookRebuildPreview:
    """Summarize editions that need the current human-audiobook pipeline."""
    editions, track_counts = await _human_audiobook_rebuild_inventory(db)
    available = [
        edition
        for edition in editions
        if edition.status == ImportedAudiobookStatus.READY.value and track_counts.get(edition.id, 0) > 0
    ]
    rebuild = [edition for edition in available if _needs_human_audiobook_rebuild(edition)]
    return HumanAudiobookRebuildPreview(
        current_pipeline_version=CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION,
        total_count=len(editions),
        rebuild_count=len(rebuild),
        realign_count=sum(
            edition.alignment_method in {AlignmentMethod.TRANSCRIBED.value, AlignmentMethod.HYBRID.value}
            or bool(edition.alignment_error)
            for edition in rebuild
        ),
        up_to_date_count=len(available) - len(rebuild),
        unavailable_count=len(editions) - len(available),
    )


@router.post("/api/audiobook/imports/rebuild-all", response_model=contracts.RebuiltImports)
async def rebuild_all_human_audiobooks(
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> contracts.RebuiltImports:
    """Queue ready editions that are behind the current rebuild pipeline."""
    editions, track_counts = await _human_audiobook_rebuild_inventory(db)
    queued = 0
    skipped = 0
    for edition in editions:
        available = edition.status == ImportedAudiobookStatus.READY.value and track_counts.get(edition.id, 0) > 0
        if not available or (not force and not _needs_human_audiobook_rebuild(edition)):
            skipped += 1
            continue
        await queue_processing_job(
            db=db,
            job_type="rebuild_imported_audiobook",
            book_id=edition.book_id,
            target_type="imported_audiobook",
            target_id=edition.id,
            target_content_version=edition.matched_content_version,
            payload=RebuildImportedAudiobookPayload(pipeline_version=CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION, force=force),
            dedupe_key=(
                f"rebuild_imported_audiobook:imported_audiobook:{edition.id}:" f"v{CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION}"
            ),
            progress_detail=f"Queued human-audiobook pipeline v{CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION}",
        )
        edition.progress_detail = "Human audiobook rebuild queued"
        queued += 1
    await db.commit()
    return {
        "queued_count": queued,
        "skipped_count": skipped,
        "pipeline_version": CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION,
    }


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
    await get_book_or_404(edition.book_id, db)
    if edition.status == "aligning":
        return await imported_audiobook_response(edition, db)
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
    transition_state(
        edition,
        "status",
        IMPORTED_AUDIOBOOK,
        ImportedAudiobookStatus.ALIGNING,
        context=f"imported audiobook {edition.id}",
    )
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
    return await imported_audiobook_response(edition, db)


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
    book = await get_book_or_404(edition.book_id, db)
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
    transition_state(
        edition,
        "status",
        IMPORTED_AUDIOBOOK,
        ImportedAudiobookStatus.STALE,
        context=f"imported audiobook {edition.id}",
    )
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
        payload=RematchImportedAudiobookPayload(realign=realign),
        dedupe_key=f"rematch_imported_audiobook:imported_audiobook:{edition.id}:v{book.content_version or 1}",
        progress_detail="Queued to restore human-audio chapter matches and text cues",
    )
    return await imported_audiobook_response(edition, db)


@router.delete("/api/imported-audiobooks/{edition_id}", status_code=204)
async def delete_imported_audiobook(
    edition_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    edition = await db.get(ImportedAudiobook, edition_id)
    if edition is None:
        raise HTTPException(status_code=404, detail="Imported audiobook not found")
    await get_book_or_404(edition.book_id, db)
    edition_dir = audiobook_import.imported_audiobook_dir(edition.book_id, edition.id)
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
    # Imported narration is independent of the opt-in AI generation pipeline.
    # Human-only books still need synchronized text and block metadata.
    book = await get_book_or_404(edition.book_id, db)
    result = await db.execute(
        select(ImportedAudiobookCue, AudiobookSentence)
        .join(AudiobookSentence, AudiobookSentence.id == ImportedAudiobookCue.sentence_id)
        .where(ImportedAudiobookCue.track_id == track.id)
        .order_by(ImportedAudiobookCue.sequence_order)
    )
    rows = result.all()
    chapter_ids = {sentence.chapter_id for _cue, sentence in rows}
    chapters = {}
    if chapter_ids:
        chapter_result = await db.execute(select(AudiobookChapter).where(AudiobookChapter.id.in_(chapter_ids)))
        chapters = {chapter.id: chapter for chapter in chapter_result.scalars().all()}
    reading_blocks = {chapter_id: chapter_reading_blocks(book, chapter) for chapter_id, chapter in chapters.items()}
    return [
        ImportedCueResponse(
            sentence_id=sentence.id,
            html_element_id=sentence.html_element_id,
            text=sentence.original_text,
            clip_begin_ms=cue.clip_begin_ms,
            clip_end_ms=cue.clip_end_ms,
            confidence=cue.confidence,
            method=cue.method,
            **reading_block_fields(reading_blocks.get(sentence.chapter_id, {}), sentence.html_element_id),
        )
        for cue, sentence in rows
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
    refreshed = await imported_audiobook_response(edition, db)
    return next(item for item in refreshed.tracks if item.id == track.id)


@router.get(
    "/api/imported-audiobooks/{edition_id}/tracks/{track_id}/audio",
    response_class=Response,
    responses=contracts.media_responses("audio/*"),
)
async def get_imported_track_audio(
    edition_id: int,
    track_id: int,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    _edition, track = await _get_imported_track_or_404(edition_id, track_id, db)
    try:
        full_path = audiobook_views.imported_track_audio_path(track)
    except AudiobookViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc
    return FileResponse(str(full_path), media_type=track.media_type)


@router.get(
    "/api/imported-audiobooks/{edition_id}/tracks/{track_id}/smil",
    response_class=Response,
    responses=contracts.media_responses("application/smil+xml", binary=False),
)
async def get_imported_track_smil(
    edition_id: int,
    track_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    edition, track = await _get_imported_track_or_404(edition_id, track_id, db)
    try:
        payload = await audiobook_views.imported_track_smil(edition, track, db)
    except AudiobookViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc
    return Response(payload, media_type="application/smil+xml")
