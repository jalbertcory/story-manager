"""Request and response models for the audiobook API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional, TypedDict

from pydantic import Field

from .api_model import APIModel as BaseModel
from .endpoint_types import EndpointStats, EndpointUpdate, SolverStats
from .services.audiobook_reading import ReadingBlock

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

# One plain-language state per audio source; see services/audiobook_status.py.
AudioState = Literal[
    "working",
    "job_failed",
    "import_failed",
    "needs_review",
    "outdated",
    "whisper_failed",
    "ready_whisper",
    "ready_estimated",
    "audio_only",
    "tts_failed",
    "tts_running",
    "tts_paused",
    "tts_outdated",
    "tts_partial",
    "tts_complete",
    "tts_not_started",
]
AudioNextAction = Literal[
    "retry_processing",
    "retry_import",
    "review_matches",
    "rebuild",
    "retry_whisper",
    "improve_with_whisper",
    "set_up_transcription",
    "open_generation",
]


# Next actions that queue work for a human edition and can run for many at once.
AudioBulkAction = Literal["retry_processing", "retry_import", "rebuild", "retry_whisper", "improve_with_whisper"]


class AudiobookBulkActionRequest(BaseModel):
    action: AudioBulkAction
    edition_ids: list[int] = Field(min_length=1, max_length=500)


class AudiobookBulkActionSkip(BaseModel):
    edition_id: int
    reason: str


class AudiobookBulkActionResponse(BaseModel):
    queued: list[int]
    skipped: list[AudiobookBulkActionSkip]


class NarrationBulkResumeRequest(BaseModel):
    book_ids: list[int] = Field(min_length=1, max_length=500)


class NarrationBulkResumeSkip(BaseModel):
    book_id: int
    reason: str


class NarrationBulkResumeResponse(BaseModel):
    queued: list[int]
    skipped: list[NarrationBulkResumeSkip]


class AudiobookStatusResponse(BaseModel):
    pipeline_status: Optional[str]
    next_phase: str
    # The book text changed after the narration was generated.
    outdated: bool
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
    tts_provider_locked: bool
    available_tts_providers: list[str]


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
    tts_seed: Optional[int]
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
    tts_seed: Optional[int] = Field(default=None, ge=0, le=2_147_483_647)
    is_narrator: Optional[bool] = None


class CharacterVoiceDesign(BaseModel):
    voice_prompt: Optional[str] = None


class BookTTSProviderUpdate(BaseModel):
    provider: str = Field(min_length=1)


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
    generation_group_id: Optional[str]
    voice_similarity: Optional[float]
    tts_attempts: Optional[int]
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
    tts_max_block_chars: int
    tts_voice_drift_margin: float
    tts_quality_attempts: int
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


class EndpointStatsResponse(BaseModel):
    endpoints: list[EndpointStats]


class AllEndpointStatsResponse(BaseModel):
    llm: list[EndpointStats]
    tts: list[EndpointStats]
    transcription: list[EndpointStats]
    solver: list[SolverStats]


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
    tts_max_block_chars: Optional[int] = Field(default=None, ge=100, le=2000)
    # Standard deviations below a voice's calibrated similarity before a take is
    # retried; 0 disables the drift and cast checks.
    tts_voice_drift_margin: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    tts_quality_attempts: Optional[int] = Field(default=None, ge=1, le=10)
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


class ReadingBlockFields(TypedDict):
    reading_block_index: int | None
    reading_block_type: str | None


def reading_block_fields(
    reading_blocks: dict[str, ReadingBlock],
    html_element_id: str,
) -> ReadingBlockFields:
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
    match_method: Optional[str]
    source_start_ms: int
    source_end_ms: int
    duration_ms: int
    media_type: str
    cue_count: int
    alignment_score: Optional[float]
    audio_url: str
    cues_url: str
    smil_url: Optional[str] = None


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
    source_size_bytes: Optional[int]
    source_manifest_sha256: Optional[str]
    derived_revision: int
    derived_format_version: int
    pipeline_version: int
    needs_upgrade: bool
    needs_rebuild: bool
    progress_current: int
    progress_total: int
    progress_detail: Optional[str]
    error: Optional[str]
    alignment_error: Optional[str]
    matching_error: Optional[str]
    created_at: datetime
    is_reader_default: bool = False
    state: AudioState
    state_label: str
    state_detail: Optional[str]
    next_action: Optional[AudioNextAction]
    next_action_label: Optional[str]
    processing_job_id: Optional[int]
    tracks: list[ImportedTrackResponse]


class AudiobookOverviewSource(BaseModel):
    kind: Literal["human", "tts"]
    edition_id: Optional[int]
    name: str
    state: AudioState
    state_label: str
    state_detail: Optional[str]
    next_action: Optional[AudioNextAction]
    next_action_label: Optional[str]
    processing_job_id: Optional[int]
    alignment_method: Optional[str]
    progress_current: int
    progress_total: int
    updated_at: Optional[datetime]


class AudiobookOverviewBook(BaseModel):
    book_id: int
    title: str
    author: str
    has_epub: bool
    audio_kind: Literal["human", "tts", "both"]
    state: AudioState
    needs_attention: bool
    sources: list[AudiobookOverviewSource]


class AudiobookOverviewCount(BaseModel):
    state: AudioState
    label: str
    count: int


class AudiobookOverviewResponse(BaseModel):
    transcription_configured: bool
    total_count: int
    attention_count: int
    counts: list[AudiobookOverviewCount]
    books: list[AudiobookOverviewBook]


class HumanAudiobookRebuildPreview(BaseModel):
    current_pipeline_version: int
    total_count: int
    rebuild_count: int
    realign_count: int
    up_to_date_count: int
    # Blocked until someone reviews the chapter matches.
    needs_review_count: int
    # Busy, or never finished importing.
    unavailable_count: int


class ImportedTrackMatchUpdate(BaseModel):
    chapter_id: Optional[int] = None


class LibationBackupPreviewRequest(BaseModel):
    source_paths: list[str] = Field(min_length=1, max_length=50_000)


class LibationExistingAudioResponse(BaseModel):
    edition_id: int
    name: str
    status: str
    source_type: str
    product_id: Optional[str] = None


class LibationBookOptionResponse(BaseModel):
    book_id: int
    book_title: str
    book_author: Optional[str] = None
    book_series: Optional[str] = None
    match_score: Optional[float] = None
    existing_audiobooks: list[LibationExistingAudioResponse] = Field(default_factory=list)


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
    candidates: list[LibationBookOptionResponse] = Field(default_factory=list)
    existing_audiobooks: list[LibationExistingAudioResponse] = Field(default_factory=list)


class LibationBackupPreviewResponse(BaseModel):
    groups: list[LibationBackupMatchResponse]
    matched_count: int
    unmatched_count: int
    ambiguous_count: int
    already_imported_count: int
    existing_audio_match_count: int
    ignored_file_count: int
    library_books: list[LibationBookOptionResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pronunciation lexicon
# ---------------------------------------------------------------------------

PronunciationScope = Literal["book", "series", "global"]


class PronunciationResponse(BaseModel):
    id: int
    scope: PronunciationScope
    book_id: Optional[int]
    series_name: Optional[str]
    term: str
    spoken: str
    case_sensitive: bool
    # False when a more specific rule for the same term wins in this book.
    active: bool
    # Sentences of this book whose narration the rule changes.
    sentence_count: int


class PronunciationListResponse(BaseModel):
    series_name: Optional[str]
    rules: list[PronunciationResponse]


class PronunciationCreate(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    spoken: str = Field(min_length=1, max_length=400)
    scope: PronunciationScope = "book"
    case_sensitive: bool = False
    # Send narrated sentences that contain the term back for new speech.
    regenerate: bool = False


class PronunciationUpdate(BaseModel):
    term: Optional[str] = Field(default=None, min_length=1, max_length=200)
    spoken: Optional[str] = Field(default=None, min_length=1, max_length=400)
    case_sensitive: Optional[bool] = None
    regenerate: bool = False


class PronunciationChange(BaseModel):
    rule: Optional[PronunciationResponse]
    # Narrated sentences sent back for new speech across every affected book.
    sentences_reset: int
    books_affected: int


class PronunciationPreview(BaseModel):
    text: str = Field(min_length=1, max_length=400)
