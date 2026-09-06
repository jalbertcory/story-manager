"""Authoritative lifecycle vocabularies and transition rules.

Persisted status columns remain strings for backward-compatible API and database
storage. This module is the single source of truth for allowed values, labels,
state groupings, recovery behavior, and valid transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Iterable, Literal, Mapping, Protocol, overload, runtime_checkable

if TYPE_CHECKING:
    from .api_schemas import LifecycleDefinition

State = str | None


class ProcessingJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELED = "canceled"


class WebImportStatus(StrEnum):
    PENDING = "pending"
    ERROR = "error"


class WebRefreshStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    ERROR = "error"


class UpdateTaskStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class MetadataJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AudiobookPipelineStatus(StrEnum):
    INGESTING = "ingesting"
    ROSTER_GENERATION = "roster_gen"
    DIARIZING = "diarizing"
    AUDIO_GENERATION = "audio_gen"
    ASSEMBLING = "assembling"
    PAUSED = "paused"
    COMPLETE = "complete"
    ERROR = "error"


class AudiobookPublicationStatus(StrEnum):
    PROCESSING = "processing"
    PARTIAL = "partial"
    COMPLETE = "complete"
    STALE = "stale"
    ERROR = "error"


class ChapterPreviewStatus(StrEnum):
    QUEUED = "queued"
    GENERATING = "generating"
    READY = "ready"
    ERROR = "error"


class ChapterGenerationStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class SentenceStatus(StrEnum):
    PENDING_DIARIZATION = "pending_diarization"
    READY_FOR_AUDIO = "ready_for_audio"
    AUDIO_QUEUED = "audio_queued"
    AUDIO_GENERATING = "audio_generating"
    AUDIO_GENERATED = "audio_generated"
    ERROR = "error"


class ImportedAudiobookStatus(StrEnum):
    QUEUED = "queued"
    IMPORTING = "importing"
    READY = "ready"
    ALIGNING = "aligning"
    STALE = "stale"
    ERROR = "error"


class AlignmentMethod(StrEnum):
    ESTIMATED = "estimated"
    TRANSCRIBED = "transcribed"
    HYBRID = "hybrid"


class InvalidStateTransition(ValueError):
    """Raised when application code attempts an impossible lifecycle change."""


@dataclass(frozen=True)
class StateMachine:
    name: str
    states: frozenset[State]
    transitions: Mapping[State, frozenset[State]]
    labels: Mapping[State, str]
    active_states: frozenset[State] = field(default_factory=frozenset)
    terminal_states: frozenset[State] = field(default_factory=frozenset)
    failure_states: frozenset[State] = field(default_factory=frozenset)
    retryable_states: frozenset[State] = field(default_factory=frozenset)
    ordered_states: tuple[State, ...] = ()
    recovery: Mapping[State, State | str] = field(default_factory=dict)
    groups: Mapping[str, frozenset[State] | tuple[State, ...]] = field(default_factory=dict)

    def normalize(self, state: State | StrEnum) -> State:
        return state.value if isinstance(state, StrEnum) else state

    def validate_state(self, state: State | StrEnum) -> State:
        normalized = self.normalize(state)
        if normalized not in self.states:
            allowed = ", ".join("null" if item is None else item for item in self.ordered_states or self.states)
            raise InvalidStateTransition(f"Unknown {self.name} state {normalized!r}; expected one of: {allowed}.")
        return normalized

    def transition(self, current: State | StrEnum, target: State | StrEnum, *, context: str | None = None) -> State:
        current_value = self.validate_state(current)
        target_value = self.validate_state(target)
        if current_value == target_value:
            return target_value
        allowed = self.transitions.get(current_value, frozenset())
        if target_value not in allowed:
            allowed_text = ", ".join("null" if item is None else item for item in sorted(allowed, key=str)) or "none"
            location = f" for {context}" if context else ""
            raise InvalidStateTransition(
                f"Invalid {self.name} transition{location}: {current_value!r} -> {target_value!r}. "
                f"Allowed next states: {allowed_text}."
            )
        return target_value

    def manifest(self) -> LifecycleDefinition:
        ordered = self.ordered_states or tuple(sorted(self.states, key=lambda value: (value is not None, str(value))))

        def ordered_subset(values: Iterable[State]) -> list[State]:
            selected = set(values)
            return [value for value in ordered if value in selected]

        return {
            "name": self.name,
            "states": [{"value": value, "label": self.labels[value]} for value in ordered],
            "active_states": ordered_subset(self.active_states),
            "terminal_states": ordered_subset(self.terminal_states),
            "failure_states": ordered_subset(self.failure_states),
            "retryable_states": ordered_subset(self.retryable_states),
            "recovery": {"null" if key is None else key: value for key, value in self.recovery.items()},
            "groups": {
                name: list(values) if isinstance(values, tuple) else ordered_subset(values)
                for name, values in self.groups.items()
            },
        }


def _values(items: Iterable[State | StrEnum]) -> frozenset[State]:
    return frozenset(item.value if isinstance(item, StrEnum) else item for item in items)


def _labels(**labels: str) -> dict[State, str]:
    return {(None if key == "null" else key): value for key, value in labels.items()}


PROCESSING_JOB = StateMachine(
    name="processing job",
    states=_values(ProcessingJobStatus),
    transitions={
        ProcessingJobStatus.QUEUED: _values(
            (
                ProcessingJobStatus.RUNNING,
                ProcessingJobStatus.COMPLETED,
                ProcessingJobStatus.ERROR,
                ProcessingJobStatus.CANCELED,
            )
        ),
        ProcessingJobStatus.RUNNING: _values(
            (
                ProcessingJobStatus.QUEUED,
                ProcessingJobStatus.COMPLETED,
                ProcessingJobStatus.ERROR,
                ProcessingJobStatus.CANCELED,
            )
        ),
        ProcessingJobStatus.ERROR: _values((ProcessingJobStatus.QUEUED,)),
        ProcessingJobStatus.CANCELED: _values((ProcessingJobStatus.QUEUED,)),
        ProcessingJobStatus.COMPLETED: frozenset(),
    },
    labels=_labels(queued="Queued", running="Running", completed="Completed", error="Failed", canceled="Canceled"),
    active_states=_values((ProcessingJobStatus.QUEUED, ProcessingJobStatus.RUNNING)),
    terminal_states=_values((ProcessingJobStatus.COMPLETED, ProcessingJobStatus.ERROR, ProcessingJobStatus.CANCELED)),
    failure_states=_values((ProcessingJobStatus.ERROR,)),
    retryable_states=_values((ProcessingJobStatus.ERROR, ProcessingJobStatus.CANCELED)),
    ordered_states=tuple(item.value for item in ProcessingJobStatus),
    recovery={
        ProcessingJobStatus.QUEUED: ProcessingJobStatus.QUEUED,
        ProcessingJobStatus.RUNNING: ProcessingJobStatus.QUEUED,
    },
    groups={
        "running": (ProcessingJobStatus.RUNNING.value,),
        "waiting": (ProcessingJobStatus.QUEUED.value,),
    },
)

WEB_IMPORT = StateMachine(
    name="web import",
    states=_values((None, *WebImportStatus)),
    transitions={
        None: _values((WebImportStatus.PENDING, WebImportStatus.ERROR)),
        WebImportStatus.PENDING: _values((None, WebImportStatus.ERROR)),
        WebImportStatus.ERROR: _values((WebImportStatus.PENDING,)),
    },
    labels=_labels(null="Ready", pending="Importing", error="Import failed"),
    active_states=_values((WebImportStatus.PENDING,)),
    terminal_states=_values((None, WebImportStatus.ERROR)),
    failure_states=_values((WebImportStatus.ERROR,)),
    retryable_states=_values((WebImportStatus.ERROR,)),
    ordered_states=(None, WebImportStatus.PENDING, WebImportStatus.ERROR),
    recovery={WebImportStatus.PENDING: WebImportStatus.PENDING},
)

WEB_REFRESH = StateMachine(
    name="web refresh",
    states=_values((None, *WebRefreshStatus)),
    transitions={
        None: _values(
            (
                WebRefreshStatus.QUEUED,
                WebRefreshStatus.PROCESSING,
                WebRefreshStatus.ERROR,
            )
        ),
        WebRefreshStatus.QUEUED: _values((WebRefreshStatus.PROCESSING, None, WebRefreshStatus.ERROR)),
        WebRefreshStatus.PROCESSING: _values((None, WebRefreshStatus.ERROR, WebRefreshStatus.QUEUED)),
        WebRefreshStatus.ERROR: _values((WebRefreshStatus.QUEUED, WebRefreshStatus.PROCESSING, None)),
    },
    labels=_labels(null="Up to date", queued="Refresh queued", processing="Refreshing", error="Refresh failed"),
    active_states=_values((WebRefreshStatus.QUEUED, WebRefreshStatus.PROCESSING)),
    terminal_states=_values((None, WebRefreshStatus.ERROR)),
    failure_states=_values((WebRefreshStatus.ERROR,)),
    retryable_states=_values((WebRefreshStatus.ERROR,)),
    ordered_states=(None, WebRefreshStatus.QUEUED, WebRefreshStatus.PROCESSING, WebRefreshStatus.ERROR),
    recovery={
        WebRefreshStatus.QUEUED: WebRefreshStatus.QUEUED,
        WebRefreshStatus.PROCESSING: WebRefreshStatus.QUEUED,
    },
)

UPDATE_TASK = StateMachine(
    name="library refresh task",
    states=_values(UpdateTaskStatus),
    transitions={
        UpdateTaskStatus.RUNNING: _values((UpdateTaskStatus.COMPLETED, UpdateTaskStatus.FAILED, UpdateTaskStatus.INTERRUPTED)),
        UpdateTaskStatus.INTERRUPTED: _values((UpdateTaskStatus.RUNNING,)),
        UpdateTaskStatus.COMPLETED: frozenset(),
        UpdateTaskStatus.FAILED: frozenset(),
    },
    labels=_labels(running="Running", completed="Completed", failed="Failed", interrupted="Interrupted"),
    active_states=_values((UpdateTaskStatus.RUNNING,)),
    terminal_states=_values((UpdateTaskStatus.COMPLETED, UpdateTaskStatus.FAILED, UpdateTaskStatus.INTERRUPTED)),
    failure_states=_values((UpdateTaskStatus.FAILED, UpdateTaskStatus.INTERRUPTED)),
    ordered_states=tuple(item.value for item in UpdateTaskStatus),
    recovery={UpdateTaskStatus.RUNNING: UpdateTaskStatus.INTERRUPTED},
)

METADATA_JOB = StateMachine(
    name="metadata sync job",
    states=_values(MetadataJobStatus),
    transitions={
        MetadataJobStatus.QUEUED: _values((MetadataJobStatus.RUNNING, MetadataJobStatus.FAILED)),
        MetadataJobStatus.RUNNING: _values((MetadataJobStatus.QUEUED, MetadataJobStatus.COMPLETED, MetadataJobStatus.FAILED)),
        MetadataJobStatus.FAILED: _values((MetadataJobStatus.QUEUED,)),
        MetadataJobStatus.COMPLETED: frozenset(),
    },
    labels=_labels(queued="Queued", running="Running", completed="Completed", failed="Failed"),
    active_states=_values((MetadataJobStatus.QUEUED, MetadataJobStatus.RUNNING)),
    terminal_states=_values((MetadataJobStatus.COMPLETED, MetadataJobStatus.FAILED)),
    failure_states=_values((MetadataJobStatus.FAILED,)),
    retryable_states=_values((MetadataJobStatus.FAILED,)),
    ordered_states=tuple(item.value for item in MetadataJobStatus),
    recovery={
        MetadataJobStatus.QUEUED: MetadataJobStatus.QUEUED,
        MetadataJobStatus.RUNNING: MetadataJobStatus.QUEUED,
    },
)

_pipeline_phases = tuple(
    item.value
    for item in (
        AudiobookPipelineStatus.INGESTING,
        AudiobookPipelineStatus.ROSTER_GENERATION,
        AudiobookPipelineStatus.DIARIZING,
        AudiobookPipelineStatus.AUDIO_GENERATION,
        AudiobookPipelineStatus.ASSEMBLING,
    )
)
_pipeline_states = _values((None, *AudiobookPipelineStatus))
_pipeline_restart_targets = _values(
    (
        *_pipeline_phases,
        AudiobookPipelineStatus.PAUSED,
        AudiobookPipelineStatus.COMPLETE,
        AudiobookPipelineStatus.ERROR,
    )
)
AUDIOBOOK_PIPELINE = StateMachine(
    name="generated audiobook pipeline",
    states=_pipeline_states,
    transitions={
        None: _pipeline_restart_targets,
        **{
            phase: _values(
                (
                    None,
                    *_pipeline_phases,
                    AudiobookPipelineStatus.PAUSED,
                    AudiobookPipelineStatus.COMPLETE,
                    AudiobookPipelineStatus.ERROR,
                )
            )
            for phase in _pipeline_phases
        },
        AudiobookPipelineStatus.PAUSED: _pipeline_restart_targets,
        AudiobookPipelineStatus.ERROR: _pipeline_restart_targets,
        AudiobookPipelineStatus.COMPLETE: _values((AudiobookPipelineStatus.PAUSED, *_pipeline_phases)),
    },
    labels=_labels(
        null="Not started",
        ingesting="Ingesting",
        roster_gen="Roster",
        diarizing="Diarizing",
        audio_gen="TTS",
        assembling="Assembly",
        paused="Paused",
        complete="Complete",
        error="Error",
    ),
    active_states=_values(_pipeline_phases),
    terminal_states=_values(
        (None, AudiobookPipelineStatus.PAUSED, AudiobookPipelineStatus.COMPLETE, AudiobookPipelineStatus.ERROR)
    ),
    failure_states=_values((AudiobookPipelineStatus.ERROR,)),
    retryable_states=_values((AudiobookPipelineStatus.ERROR, AudiobookPipelineStatus.PAUSED)),
    ordered_states=(None, *_pipeline_phases, "paused", "complete", "error"),
    recovery={phase: phase for phase in _pipeline_phases},
    groups={
        "progress_steps": (*_pipeline_phases, AudiobookPipelineStatus.COMPLETE.value),
        "batchable": (
            AudiobookPipelineStatus.DIARIZING.value,
            AudiobookPipelineStatus.AUDIO_GENERATION.value,
            AudiobookPipelineStatus.ASSEMBLING.value,
        ),
        "concurrent_analysis": (AudiobookPipelineStatus.DIARIZING.value,),
        "ready": (AudiobookPipelineStatus.COMPLETE.value,),
        "paused": (AudiobookPipelineStatus.PAUSED.value,),
    },
)

AUDIOBOOK_PUBLICATION = StateMachine(
    name="audiobook publication",
    states=_values((None, *AudiobookPublicationStatus)),
    transitions={state: _values(AudiobookPublicationStatus) for state in (None, *AudiobookPublicationStatus)},
    labels=_labels(
        null="Unavailable", processing="Processing", partial="Partial", complete="Complete", stale="Stale", error="Error"
    ),
    active_states=_values((AudiobookPublicationStatus.PROCESSING,)),
    terminal_states=_values(
        (
            None,
            AudiobookPublicationStatus.PARTIAL,
            AudiobookPublicationStatus.COMPLETE,
            AudiobookPublicationStatus.STALE,
            AudiobookPublicationStatus.ERROR,
        )
    ),
    failure_states=_values((AudiobookPublicationStatus.ERROR, AudiobookPublicationStatus.STALE)),
    ordered_states=(None, *tuple(item.value for item in AudiobookPublicationStatus)),
    recovery={AudiobookPublicationStatus.PROCESSING: AudiobookPublicationStatus.STALE},
)

CHAPTER_PREVIEW = StateMachine(
    name="chapter preview",
    states=_values((None, *ChapterPreviewStatus)),
    transitions={
        None: _values((ChapterPreviewStatus.QUEUED,)),
        ChapterPreviewStatus.QUEUED: _values((ChapterPreviewStatus.GENERATING, ChapterPreviewStatus.ERROR, None)),
        ChapterPreviewStatus.GENERATING: _values(
            (ChapterPreviewStatus.READY, ChapterPreviewStatus.ERROR, ChapterPreviewStatus.QUEUED, None)
        ),
        ChapterPreviewStatus.READY: _values((ChapterPreviewStatus.QUEUED, None)),
        ChapterPreviewStatus.ERROR: _values((ChapterPreviewStatus.QUEUED, None)),
    },
    labels=_labels(null="Not generated", queued="Queued", generating="Generating", ready="Ready", error="Error"),
    active_states=_values((ChapterPreviewStatus.QUEUED, ChapterPreviewStatus.GENERATING)),
    terminal_states=_values((None, ChapterPreviewStatus.READY, ChapterPreviewStatus.ERROR)),
    failure_states=_values((ChapterPreviewStatus.ERROR,)),
    retryable_states=_values((ChapterPreviewStatus.ERROR,)),
    ordered_states=(None, *tuple(item.value for item in ChapterPreviewStatus)),
    recovery={
        ChapterPreviewStatus.QUEUED: ChapterPreviewStatus.QUEUED,
        ChapterPreviewStatus.GENERATING: ChapterPreviewStatus.QUEUED,
    },
    groups={
        "waiting": (ChapterPreviewStatus.QUEUED.value,),
        "working": (ChapterPreviewStatus.GENERATING.value,),
    },
)

CHAPTER_GENERATION = StateMachine(
    name="published audiobook chapter",
    states=_values(ChapterGenerationStatus),
    transitions={
        ChapterGenerationStatus.PENDING: _values(
            (ChapterGenerationStatus.PROCESSING, ChapterGenerationStatus.READY, ChapterGenerationStatus.ERROR)
        ),
        ChapterGenerationStatus.PROCESSING: _values(
            (ChapterGenerationStatus.PENDING, ChapterGenerationStatus.READY, ChapterGenerationStatus.ERROR)
        ),
        ChapterGenerationStatus.READY: _values(
            (ChapterGenerationStatus.PENDING, ChapterGenerationStatus.PROCESSING, ChapterGenerationStatus.ERROR)
        ),
        ChapterGenerationStatus.ERROR: _values((ChapterGenerationStatus.PENDING, ChapterGenerationStatus.PROCESSING)),
    },
    labels=_labels(pending="Pending", processing="Processing", ready="Ready", error="Error"),
    active_states=_values((ChapterGenerationStatus.PENDING, ChapterGenerationStatus.PROCESSING)),
    terminal_states=_values((ChapterGenerationStatus.READY, ChapterGenerationStatus.ERROR)),
    failure_states=_values((ChapterGenerationStatus.ERROR,)),
    retryable_states=_values((ChapterGenerationStatus.ERROR,)),
    ordered_states=tuple(item.value for item in ChapterGenerationStatus),
    recovery={
        ChapterGenerationStatus.PENDING: ChapterGenerationStatus.PENDING,
        ChapterGenerationStatus.PROCESSING: ChapterGenerationStatus.PENDING,
    },
)

SENTENCE = StateMachine(
    name="audiobook sentence",
    states=_values(SentenceStatus),
    transitions={
        SentenceStatus.PENDING_DIARIZATION: _values((SentenceStatus.READY_FOR_AUDIO, SentenceStatus.ERROR)),
        SentenceStatus.READY_FOR_AUDIO: _values(
            (
                SentenceStatus.AUDIO_QUEUED,
                SentenceStatus.AUDIO_GENERATING,
                SentenceStatus.AUDIO_GENERATED,
                SentenceStatus.ERROR,
                SentenceStatus.PENDING_DIARIZATION,
            )
        ),
        SentenceStatus.AUDIO_QUEUED: _values(
            (SentenceStatus.AUDIO_GENERATING, SentenceStatus.READY_FOR_AUDIO, SentenceStatus.ERROR)
        ),
        SentenceStatus.AUDIO_GENERATING: _values(
            (SentenceStatus.AUDIO_GENERATED, SentenceStatus.READY_FOR_AUDIO, SentenceStatus.ERROR)
        ),
        SentenceStatus.AUDIO_GENERATED: _values(
            (SentenceStatus.READY_FOR_AUDIO, SentenceStatus.PENDING_DIARIZATION, SentenceStatus.ERROR)
        ),
        SentenceStatus.ERROR: _values(
            (
                SentenceStatus.READY_FOR_AUDIO,
                SentenceStatus.AUDIO_QUEUED,
                SentenceStatus.AUDIO_GENERATING,
                SentenceStatus.PENDING_DIARIZATION,
            )
        ),
    },
    labels=_labels(
        pending_diarization="Pending diarization",
        ready_for_audio="Ready for audio",
        audio_queued="Audio queued",
        audio_generating="Generating audio",
        audio_generated="Audio generated",
        error="Error",
    ),
    active_states=_values((SentenceStatus.PENDING_DIARIZATION, SentenceStatus.AUDIO_QUEUED, SentenceStatus.AUDIO_GENERATING)),
    terminal_states=_values((SentenceStatus.READY_FOR_AUDIO, SentenceStatus.AUDIO_GENERATED, SentenceStatus.ERROR)),
    failure_states=_values((SentenceStatus.ERROR,)),
    retryable_states=_values((SentenceStatus.ERROR,)),
    ordered_states=tuple(item.value for item in SentenceStatus),
    recovery={
        SentenceStatus.PENDING_DIARIZATION: SentenceStatus.PENDING_DIARIZATION,
        SentenceStatus.AUDIO_QUEUED: SentenceStatus.READY_FOR_AUDIO,
        SentenceStatus.AUDIO_GENERATING: SentenceStatus.READY_FOR_AUDIO,
    },
    groups={
        "audio_in_progress": (
            SentenceStatus.AUDIO_QUEUED.value,
            SentenceStatus.AUDIO_GENERATING.value,
        ),
        "audio_ready": (SentenceStatus.READY_FOR_AUDIO.value,),
        "audio_waiting": (SentenceStatus.AUDIO_QUEUED.value,),
        "audio_working": (SentenceStatus.AUDIO_GENERATING.value,),
        "audio_playable": (SentenceStatus.AUDIO_GENERATED.value,),
    },
)

IMPORTED_AUDIOBOOK = StateMachine(
    name="imported audiobook",
    states=_values(ImportedAudiobookStatus),
    transitions={
        ImportedAudiobookStatus.QUEUED: _values(
            (ImportedAudiobookStatus.IMPORTING, ImportedAudiobookStatus.STALE, ImportedAudiobookStatus.ERROR)
        ),
        ImportedAudiobookStatus.IMPORTING: _values(
            (
                ImportedAudiobookStatus.READY,
                ImportedAudiobookStatus.STALE,
                ImportedAudiobookStatus.ERROR,
                ImportedAudiobookStatus.QUEUED,
            )
        ),
        ImportedAudiobookStatus.READY: _values(
            (ImportedAudiobookStatus.ALIGNING, ImportedAudiobookStatus.STALE, ImportedAudiobookStatus.IMPORTING)
        ),
        ImportedAudiobookStatus.ALIGNING: _values(
            (ImportedAudiobookStatus.READY, ImportedAudiobookStatus.STALE, ImportedAudiobookStatus.ERROR)
        ),
        ImportedAudiobookStatus.STALE: _values(
            (ImportedAudiobookStatus.IMPORTING, ImportedAudiobookStatus.READY, ImportedAudiobookStatus.ALIGNING)
        ),
        ImportedAudiobookStatus.ERROR: _values(
            (ImportedAudiobookStatus.QUEUED, ImportedAudiobookStatus.IMPORTING, ImportedAudiobookStatus.STALE)
        ),
    },
    labels=_labels(queued="Queued", importing="Importing", ready="Ready", aligning="Aligning", stale="Stale", error="Error"),
    active_states=_values(
        (
            ImportedAudiobookStatus.QUEUED,
            ImportedAudiobookStatus.IMPORTING,
            ImportedAudiobookStatus.ALIGNING,
            ImportedAudiobookStatus.STALE,
        )
    ),
    terminal_states=_values((ImportedAudiobookStatus.READY, ImportedAudiobookStatus.ERROR)),
    failure_states=_values((ImportedAudiobookStatus.ERROR, ImportedAudiobookStatus.STALE)),
    retryable_states=_values((ImportedAudiobookStatus.ERROR, ImportedAudiobookStatus.STALE)),
    ordered_states=tuple(item.value for item in ImportedAudiobookStatus),
    recovery={
        ImportedAudiobookStatus.QUEUED: ImportedAudiobookStatus.QUEUED,
        ImportedAudiobookStatus.IMPORTING: ImportedAudiobookStatus.QUEUED,
        ImportedAudiobookStatus.ALIGNING: ImportedAudiobookStatus.READY,
        ImportedAudiobookStatus.STALE: ImportedAudiobookStatus.STALE,
    },
)

ALIGNMENT_METHOD = StateMachine(
    name="audiobook alignment method",
    states=_values((None, *AlignmentMethod)),
    transitions={state: _values((None, *AlignmentMethod)) for state in (None, *AlignmentMethod)},
    labels=_labels(null="Not aligned", estimated="Estimated", transcribed="Transcribed", hybrid="Hybrid"),
    terminal_states=_values((None, *AlignmentMethod)),
    ordered_states=(None, *tuple(item.value for item in AlignmentMethod)),
)

LIFECYCLES: Mapping[str, StateMachine] = {
    "processing_job": PROCESSING_JOB,
    "web_import": WEB_IMPORT,
    "web_refresh": WEB_REFRESH,
    "update_task": UPDATE_TASK,
    "metadata_job": METADATA_JOB,
    "audiobook_pipeline": AUDIOBOOK_PIPELINE,
    "audiobook_publication": AUDIOBOOK_PUBLICATION,
    "chapter_preview": CHAPTER_PREVIEW,
    "chapter_generation": CHAPTER_GENERATION,
    "sentence": SENTENCE,
    "imported_audiobook": IMPORTED_AUDIOBOOK,
    "alignment_method": ALIGNMENT_METHOD,
}


@runtime_checkable
class HasDownloadStatus(Protocol):
    download_status: str | None


@runtime_checkable
class HasRefreshStatus(Protocol):
    refresh_status: str | None


@runtime_checkable
class HasAudiobookPipelineStatus(Protocol):
    audiobook_pipeline_status: str | None


@runtime_checkable
class HasAudiobookPublicationState(Protocol):
    audiobook_publication_state: str | None


@runtime_checkable
class HasPreviewStatus(Protocol):
    preview_status: str | None


@runtime_checkable
class HasGenerationState(Protocol):
    generation_state: str


@runtime_checkable
class HasAlignmentMethod(Protocol):
    alignment_method: str | None


@runtime_checkable
class HasStatus(Protocol):
    status: str


@overload
def transition_state(
    record: HasDownloadStatus,
    attribute: Literal["download_status"],
    machine: StateMachine,
    target: State | StrEnum,
    *,
    context: str | None = None,
) -> State: ...


@overload
def transition_state(
    record: HasRefreshStatus,
    attribute: Literal["refresh_status"],
    machine: StateMachine,
    target: State | StrEnum,
    *,
    context: str | None = None,
) -> State: ...


@overload
def transition_state(
    record: HasAudiobookPipelineStatus,
    attribute: Literal["audiobook_pipeline_status"],
    machine: StateMachine,
    target: State | StrEnum,
    *,
    context: str | None = None,
) -> State: ...


@overload
def transition_state(
    record: HasAudiobookPublicationState,
    attribute: Literal["audiobook_publication_state"],
    machine: StateMachine,
    target: State | StrEnum,
    *,
    context: str | None = None,
) -> State: ...


@overload
def transition_state(
    record: HasPreviewStatus,
    attribute: Literal["preview_status"],
    machine: StateMachine,
    target: State | StrEnum,
    *,
    context: str | None = None,
) -> State: ...


@overload
def transition_state(
    record: HasGenerationState,
    attribute: Literal["generation_state"],
    machine: StateMachine,
    target: State | StrEnum,
    *,
    context: str | None = None,
) -> State: ...


@overload
def transition_state(
    record: HasAlignmentMethod,
    attribute: Literal["alignment_method"],
    machine: StateMachine,
    target: State | StrEnum,
    *,
    context: str | None = None,
) -> State: ...


@overload
def transition_state(
    record: HasStatus,
    attribute: Literal["status"],
    machine: StateMachine,
    target: State | StrEnum,
    *,
    context: str | None = None,
) -> State: ...


def transition_state(
    record: object,
    attribute: str,
    machine: StateMachine,
    target: State | StrEnum,
    *,
    context: str | None = None,
) -> State:
    """Validate lifecycle changes through statically checked record/field pairs."""
    location = context or f"{type(record).__name__}.{attribute}"

    if attribute == "download_status" and isinstance(record, HasDownloadStatus):
        value = machine.transition(record.download_status, target, context=location)
        record.download_status = value
        return value

    if attribute == "refresh_status" and isinstance(record, HasRefreshStatus):
        value = machine.transition(record.refresh_status, target, context=location)
        record.refresh_status = value
        return value

    if attribute == "audiobook_pipeline_status" and isinstance(record, HasAudiobookPipelineStatus):
        value = machine.transition(record.audiobook_pipeline_status, target, context=location)
        record.audiobook_pipeline_status = value
        return value

    if attribute == "audiobook_publication_state" and isinstance(record, HasAudiobookPublicationState):
        value = machine.transition(record.audiobook_publication_state, target, context=location)
        record.audiobook_publication_state = value
        return value

    if attribute == "preview_status" and isinstance(record, HasPreviewStatus):
        value = machine.transition(record.preview_status, target, context=location)
        record.preview_status = value
        return value

    if attribute == "generation_state" and isinstance(record, HasGenerationState):
        value = machine.transition(record.generation_state, target, context=location)
        if value is None:
            raise InvalidStateTransition(f"{location} cannot be null.")
        record.generation_state = value
        return value

    if attribute == "alignment_method" and isinstance(record, HasAlignmentMethod):
        value = machine.transition(record.alignment_method, target, context=location)
        record.alignment_method = value
        return value

    if attribute == "status" and isinstance(record, HasStatus):
        value = machine.transition(record.status, target, context=location)
        if value is None:
            raise InvalidStateTransition(f"{location} cannot be null.")
        record.status = value
        return value

    raise TypeError(f"Unsupported lifecycle field {location}.")


def lifecycle_manifest() -> dict[str, LifecycleDefinition]:
    """Return the documented vocabulary consumed by frontend labels/groupings."""
    return {name: machine.manifest() for name, machine in LIFECYCLES.items()}
