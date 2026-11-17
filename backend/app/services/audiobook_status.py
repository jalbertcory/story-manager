"""One plain-language status and next step for every audiobook source.

Human editions keep several raw signals: a lifecycle ``status``, an import
``error``, an ``alignment_error``, a live chapter-matching check and version
numbers. AI narration keeps a pipeline phase and a publication state. The rules
below turn those into a single state with at most one action, so the library
overview, the Needs Attention dashboard and a book's Sources tab describe a
source the same way. Within each function the first matching rule wins.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..audiobook_schemas import (
    AudioNextAction,
    AudiobookOverviewBook,
    AudiobookOverviewCount,
    AudiobookOverviewResponse,
    AudiobookOverviewSource,
    AudioState,
)
from ..lifecycle import (
    AlignmentMethod,
    AudiobookPipelineStatus,
    AudiobookPublicationStatus,
    ImportedAudiobookStatus,
    ProcessingJobStatus,
)
from ..models import Book, ImportedAudiobook, ProcessingJob
from .audiobook_import import CURRENT_DERIVED_FORMAT_VERSION, CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION
from .audiobook_match_validation import MATCH_REVIEW_PREFIX, imported_matching_errors
from .transcription_providers import transcription_provider_name

# Most urgent first: the overview sorts and rolls books up by this order.
STATE_ORDER: tuple[AudioState, ...] = (
    "import_failed",
    "tts_failed",
    "needs_review",
    "whisper_failed",
    "outdated",
    "tts_outdated",
    "tts_paused",
    "working",
    "tts_running",
    "tts_partial",
    "tts_not_started",
    "ready_estimated",
    "ready_whisper",
    "tts_complete",
    "audio_only",
)
# Names for whole groups of sources, used by the overview's filters.
STATE_LABELS: dict[AudioState, str] = {
    "import_failed": "Import failed",
    "tts_failed": "AI narration failed",
    "needs_review": "Needs match review",
    "whisper_failed": "Whisper failed",
    "outdated": "Needs rebuild",
    "tts_outdated": "AI narration outdated",
    "tts_paused": "AI narration paused",
    "working": "In progress",
    "tts_running": "Generating AI narration",
    "tts_partial": "AI narration (partial)",
    "tts_not_started": "AI narration not started",
    "ready_estimated": "Human audio",
    "ready_whisper": "Human audio + Whisper",
    "tts_complete": "AI narration",
    "audio_only": "Audio only",
}
# Something is wrong or out of date and only the owner can move it forward.
ATTENTION_STATES: frozenset[AudioState] = frozenset(
    {"import_failed", "tts_failed", "needs_review", "whisper_failed", "outdated", "tts_outdated"}
)
# Listening along with the text is blocked until the owner acts.
BLOCKING_STATES: frozenset[AudioState] = frozenset({"import_failed", "tts_failed", "needs_review"})

_WORKING_LABELS = {
    ImportedAudiobookStatus.QUEUED.value: "Queued",
    ImportedAudiobookStatus.IMPORTING.value: "Importing",
    ImportedAudiobookStatus.STALE.value: "Rematching",
    ImportedAudiobookStatus.ALIGNING.value: "Running Whisper",
}
_TTS_PHASES = frozenset(
    {
        AudiobookPipelineStatus.INGESTING.value,
        AudiobookPipelineStatus.ROSTER_GENERATION.value,
        AudiobookPipelineStatus.DIARIZING.value,
        AudiobookPipelineStatus.AUDIO_GENERATION.value,
        AudiobookPipelineStatus.ASSEMBLING.value,
    }
)
_ACTIVE_JOB_STATUSES = (ProcessingJobStatus.QUEUED.value, ProcessingJobStatus.RUNNING.value)


@dataclass(frozen=True)
class AudioStatus:
    state: AudioState
    label: str
    detail: str | None = None
    next_action: AudioNextAction | None = None
    action_label: str | None = None


def state_rank(state: AudioState) -> int:
    return STATE_ORDER.index(state)


def is_match_review_error(message: str | None) -> bool:
    return bool(message and message.startswith(MATCH_REVIEW_PREFIX))


def needs_match_check(edition: ImportedAudiobook) -> bool:
    """Only a ready edition's state depends on the live chapter-matching check."""
    return edition.status == ImportedAudiobookStatus.READY.value


def _outdated_reason(edition: ImportedAudiobook, content_version: int) -> str | None:
    if (edition.pipeline_version or 0) < CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION:
        return (
            f"Built with audiobook pipeline v{edition.pipeline_version or 0}; "
            f"v{CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION} matches chapters more reliably."
        )
    if not edition.source_manifest_sha256 or (edition.derived_format_version or 0) < CURRENT_DERIVED_FORMAT_VERSION:
        return "Chapter audio files use an older format."
    if edition.matched_content_version is not None and edition.matched_content_version != content_version:
        return "Matched to an older version of the book text."
    return None


def human_edition_status(
    edition: ImportedAudiobook,
    *,
    has_epub: bool,
    content_version: int,
    matching_error: str | None,
    transcription_configured: bool,
) -> AudioStatus:
    """Collapse a human edition's raw fields into one state and next action.

    ``content_version`` is the book's current text version (``content_version
    or 1``, as imports record it). ``matching_error`` is the live
    chapter-matching check, which only matters once the edition is ready.
    """
    status = edition.status
    if status in _WORKING_LABELS:
        return AudioStatus("working", _WORKING_LABELS[status], edition.progress_detail)
    if status == ImportedAudiobookStatus.ERROR.value:
        # Import, rematch and alignment all prefix match-safety failures. Any
        # other error means the audio did not finish importing, even when some
        # tracks were written before it failed.
        if is_match_review_error(edition.error):
            return AudioStatus("needs_review", "Needs match review", edition.error, "review_matches", "Review matches")
        return AudioStatus(
            "import_failed",
            "Import failed",
            edition.error or edition.alignment_error or "The import stopped before it finished.",
            "retry_import",
            "Retry import",
        )
    if not has_epub:
        return AudioStatus("audio_only", "Audio only", "This book has no EPUB text to read along with.")
    if matching_error:
        return AudioStatus("needs_review", "Needs match review", matching_error, "review_matches", "Review matches")
    outdated = _outdated_reason(edition, content_version)
    if outdated:
        return AudioStatus("outdated", "Needs rebuild", outdated, "rebuild", "Rebuild")
    if edition.alignment_error and transcription_configured:
        return AudioStatus("whisper_failed", "Whisper failed", edition.alignment_error, "retry_whisper", "Retry Whisper")
    if edition.alignment_method == AlignmentMethod.TRANSCRIBED.value:
        return AudioStatus("ready_whisper", "Human audio + Whisper", "Sentence timing comes from Whisper.")
    if edition.alignment_method == AlignmentMethod.HYBRID.value:
        return AudioStatus(
            "ready_whisper",
            "Human audio + Whisper",
            "Sentence timing comes from Whisper; uncertain passages keep estimated timing.",
        )
    if transcription_configured:
        return AudioStatus(
            "ready_estimated",
            "Human audio",
            "Sentence timing is estimated from text length.",
            "improve_with_whisper",
            "Improve with Whisper",
        )
    return AudioStatus(
        "ready_estimated",
        "Human audio",
        "Sentence timing is estimated from text length. Add a transcription provider to align it with Whisper.",
        "set_up_transcription",
        "Set up transcription",
    )


def tts_status(book: Book, *, job_active: bool) -> AudioStatus | None:
    """State of the AI-generated narration, or None when it is not enabled."""
    if not book.audiobook_enabled:
        return None
    pipeline = book.audiobook_pipeline_status
    publication = book.audiobook_publication_state
    if pipeline == AudiobookPipelineStatus.ERROR.value:
        return AudioStatus(
            "tts_failed",
            "Failed",
            book.audiobook_last_error or "The narration pipeline stopped with an error.",
            "open_generation",
            "Review and retry",
        )
    if job_active:
        return AudioStatus("tts_running", "Generating", book.audiobook_progress_detail)
    if pipeline == AudiobookPipelineStatus.PAUSED.value or pipeline in _TTS_PHASES:
        # A phase with no queued job was paused or stopped after a single step.
        return AudioStatus("tts_paused", "Paused", book.audiobook_progress_detail, "open_generation", "Resume")
    if publication == AudiobookPublicationStatus.STALE.value or book.audiobook_pending_content_version is not None:
        return AudioStatus(
            "tts_outdated",
            "Outdated",
            "The book text changed after this narration was generated.",
            "open_generation",
            "Update narration",
        )
    if publication == AudiobookPublicationStatus.COMPLETE.value:
        return AudioStatus("tts_complete", "Ready")
    if publication == AudiobookPublicationStatus.PARTIAL.value:
        return AudioStatus("tts_partial", "Partial", "Some chapters have narration.", "open_generation", "Continue")
    return AudioStatus("tts_not_started", "Not started", None, "open_generation", "Start")


async def transcription_configured(db: AsyncSession) -> bool:
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None:
        return False
    try:
        return transcription_provider_name(settings) != "none"
    except RuntimeError:
        return False  # An unsupported provider cannot run Whisper either.


def _source(
    status: AudioStatus,
    *,
    kind: Literal["human", "tts"],
    edition_id: int | None,
    name: str,
    alignment_method: str | None,
    progress_current: int,
    progress_total: int,
    updated_at: datetime | None,
) -> AudiobookOverviewSource:
    return AudiobookOverviewSource(
        kind=kind,
        edition_id=edition_id,
        name=name,
        state=status.state,
        state_label=status.label,
        state_detail=status.detail,
        next_action=status.next_action,
        next_action_label=status.action_label,
        alignment_method=alignment_method,
        progress_current=progress_current,
        progress_total=progress_total,
        updated_at=updated_at,
    )


async def audiobook_overview(db: AsyncSession) -> AudiobookOverviewResponse:
    """Every live book with human or AI audio, most urgent first.

    Uses a fixed number of queries however many books the library holds.
    """
    configured = await transcription_configured(db)
    editions = list(
        (
            await db.scalars(
                select(ImportedAudiobook)
                .join(Book, Book.id == ImportedAudiobook.book_id)
                .where(Book.deleted_at.is_(None))
                .order_by(ImportedAudiobook.created_at.desc(), ImportedAudiobook.id.desc())
            )
        ).all()
    )
    books = {
        book.id: book
        for book in (
            await db.scalars(
                select(Book).where(
                    Book.deleted_at.is_(None),
                    Book.audiobook_enabled.is_(True) | Book.id.in_({edition.book_id for edition in editions}),
                )
            )
        ).all()
    }
    matching = await imported_matching_errors([edition for edition in editions if needs_match_check(edition)], db)
    active_tts = set(
        (
            await db.scalars(
                select(ProcessingJob.book_id)
                .where(
                    ProcessingJob.job_type == "audiobook_pipeline",
                    ProcessingJob.status.in_(_ACTIVE_JOB_STATUSES),
                    ProcessingJob.book_id.in_(books.keys()),
                )
                .distinct()
            )
        ).all()
    )

    sources: dict[int, list[AudiobookOverviewSource]] = {book_id: [] for book_id in books}
    for edition in editions:
        book = books.get(edition.book_id)
        if book is None:
            continue
        status = human_edition_status(
            edition,
            has_epub=bool(book.current_path),
            content_version=book.content_version or 1,
            matching_error=matching.get(edition.id),
            transcription_configured=configured,
        )
        sources[book.id].append(
            _source(
                status,
                kind="human",
                edition_id=edition.id,
                name=edition.name or "Imported audiobook",
                alignment_method=edition.alignment_method,
                progress_current=edition.progress_current or 0,
                progress_total=edition.progress_total or 0,
                updated_at=edition.updated_at,
            )
        )
    for book in books.values():
        tts = tts_status(book, job_active=book.id in active_tts)
        if tts is not None:
            sources[book.id].append(
                _source(
                    tts,
                    kind="tts",
                    edition_id=None,
                    name="AI narration",
                    alignment_method=None,
                    progress_current=book.audiobook_progress_current or 0,
                    progress_total=book.audiobook_progress_total or 0,
                    updated_at=book.audiobook_pipeline_updated_at,
                )
            )

    rows: list[AudiobookOverviewBook] = []
    for book_id, book_sources in sources.items():
        if not book_sources:
            continue
        book = books[book_id]
        book_sources.sort(key=lambda source: state_rank(source.state))
        kinds = {source.kind for source in book_sources}
        rows.append(
            AudiobookOverviewBook(
                book_id=book.id,
                title=book.title or "",
                author=book.author or "",
                has_epub=bool(book.current_path),
                audio_kind="both" if len(kinds) > 1 else ("tts" if "tts" in kinds else "human"),
                state=book_sources[0].state,
                needs_attention=any(source.state in ATTENTION_STATES for source in book_sources),
                sources=book_sources,
            )
        )
    rows.sort(key=lambda row: (state_rank(row.state), row.title.casefold(), row.book_id))
    counts: Counter[AudioState] = Counter(state for row in rows for state in {source.state for source in row.sources})
    return AudiobookOverviewResponse(
        transcription_configured=configured,
        total_count=len(rows),
        attention_count=sum(row.needs_attention for row in rows),
        counts=[
            AudiobookOverviewCount(state=state, label=STATE_LABELS[state], count=counts[state])
            for state in STATE_ORDER
            if counts[state]
        ],
        books=rows,
    )
