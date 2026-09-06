"""Per-job payload contracts shared by HTTP ingress, queue persistence and workers.

Validate again when reading durable jobs: older rows can predate these contracts.
Defaults preserve worker behavior for historical empty payloads. Producers pass
models to queue_processing_job, e.g. ImportAudiobookPayload(auto_align=False).
The job_type discriminator binds HTTP payloads to these same schemas; extra keys
and scalar coercion are forbidden. Raw JSON is retained for ledger display so a
malformed historical job can still be inspected without becoming runnable.
"""

from __future__ import annotations

from typing import Annotated, Generic, Literal, TypeVar
from pydantic import ConfigDict, Field
from .api_model import APIModel


class JobPayload(APIModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CleanBookPayload(JobPayload):
    pass


class CleanAllPayload(JobPayload):
    reason: str | None = None


class RefreshBookPayload(JobPayload):
    pass


class RefreshAllPayload(JobPayload):
    trigger: str = "manual"


class ImportWebBookPayload(JobPayload):
    source_url: str = Field(min_length=1)


class AudiobookPipelinePayload(JobPayload):
    mode: Literal["resume", "reconcile", "rebuild", "audio", "roster", "step", "batch"] = "resume"


class ImportAudiobookPayload(JobPayload):
    auto_align: bool = True


class UpgradeImportedAudiobookPayload(JobPayload):
    format_version: int | None = Field(default=None, gt=0)


class RebuildImportedAudiobookPayload(JobPayload):
    pipeline_version: int | None = Field(default=None, gt=0)
    force: bool = False


class RematchImportedAudiobookPayload(JobPayload):
    realign: bool = False


class AlignImportedAudiobookPayload(JobPayload):
    pass


class MetadataSyncPayload(JobPayload):
    metadata_job_id: int | None = Field(default=None, gt=0)
    trigger: str = "manual"


class GenerateSentenceAudioPayload(JobPayload):
    pass


class GenerateChapterPreviewPayload(JobPayload):
    pass


class RetryCoverPayload(JobPayload):
    pass


class CreateBackupPayload(JobPayload):
    pass


class VerifyBackupPayload(JobPayload):
    filename: str = Field(min_length=1)


JOB_PAYLOAD_MODELS: dict[str, type[JobPayload]] = {
    "clean_book": CleanBookPayload,
    "clean_all": CleanAllPayload,
    "refresh_book": RefreshBookPayload,
    "refresh_all": RefreshAllPayload,
    "import_web_book": ImportWebBookPayload,
    "audiobook_pipeline": AudiobookPipelinePayload,
    "import_audiobook": ImportAudiobookPayload,
    "upgrade_imported_audiobook": UpgradeImportedAudiobookPayload,
    "rebuild_imported_audiobook": RebuildImportedAudiobookPayload,
    "rematch_imported_audiobook": RematchImportedAudiobookPayload,
    "align_imported_audiobook": AlignImportedAudiobookPayload,
    "metadata_sync": MetadataSyncPayload,
    "generate_sentence_audio": GenerateSentenceAudioPayload,
    "generate_chapter_preview": GenerateChapterPreviewPayload,
    "retry_cover": RetryCoverPayload,
    "create_backup": CreateBackupPayload,
    "verify_backup": VerifyBackupPayload,
}


def validate_job_payload(job_type: str, payload: object) -> JobPayload:
    try:
        schema = JOB_PAYLOAD_MODELS[job_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported processing job type: {job_type}") from exc
    if isinstance(payload, JobPayload):
        if not isinstance(payload, schema):
            raise ValueError(f"{job_type} requires {schema.__name__}, not {type(payload).__name__}")
        payload = payload.model_dump(exclude_unset=True)
    return schema.model_validate({} if payload is None else payload)


_Payload = TypeVar("_Payload", bound=JobPayload)


class JobRequest(APIModel, Generic[_Payload]):
    model_config = ConfigDict(extra="forbid")
    book_ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(default_factory=list)
    target_id: Annotated[int, Field(strict=True, gt=0)] | None = None
    payload: _Payload


class CleanBookRequest(JobRequest[CleanBookPayload]):
    job_type: Literal["clean_book"]
    payload: CleanBookPayload = Field(default_factory=CleanBookPayload)


class CleanAllRequest(JobRequest[CleanAllPayload]):
    job_type: Literal["clean_all"]
    payload: CleanAllPayload = Field(default_factory=CleanAllPayload)


class RefreshBookRequest(JobRequest[RefreshBookPayload]):
    job_type: Literal["refresh_book"]
    payload: RefreshBookPayload = Field(default_factory=RefreshBookPayload)


class RefreshAllRequest(JobRequest[RefreshAllPayload]):
    job_type: Literal["refresh_all"]
    payload: RefreshAllPayload = Field(default_factory=RefreshAllPayload)


class AudiobookPipelineRequest(JobRequest[AudiobookPipelinePayload]):
    job_type: Literal["audiobook_pipeline"]
    payload: AudiobookPipelinePayload = Field(default_factory=AudiobookPipelinePayload)


class ImportAudiobookRequest(JobRequest[ImportAudiobookPayload]):
    job_type: Literal["import_audiobook"]
    payload: ImportAudiobookPayload = Field(default_factory=ImportAudiobookPayload)


class UpgradeImportedAudiobookRequest(JobRequest[UpgradeImportedAudiobookPayload]):
    job_type: Literal["upgrade_imported_audiobook"]
    payload: UpgradeImportedAudiobookPayload = Field(default_factory=UpgradeImportedAudiobookPayload)


class RebuildImportedAudiobookRequest(JobRequest[RebuildImportedAudiobookPayload]):
    job_type: Literal["rebuild_imported_audiobook"]
    payload: RebuildImportedAudiobookPayload = Field(default_factory=RebuildImportedAudiobookPayload)


class RematchImportedAudiobookRequest(JobRequest[RematchImportedAudiobookPayload]):
    job_type: Literal["rematch_imported_audiobook"]
    payload: RematchImportedAudiobookPayload = Field(default_factory=RematchImportedAudiobookPayload)


class AlignImportedAudiobookRequest(JobRequest[AlignImportedAudiobookPayload]):
    job_type: Literal["align_imported_audiobook"]
    payload: AlignImportedAudiobookPayload = Field(default_factory=AlignImportedAudiobookPayload)


class MetadataSyncRequest(JobRequest[MetadataSyncPayload]):
    job_type: Literal["metadata_sync"]
    payload: MetadataSyncPayload = Field(default_factory=MetadataSyncPayload)


class GenerateSentenceAudioRequest(JobRequest[GenerateSentenceAudioPayload]):
    job_type: Literal["generate_sentence_audio"]
    payload: GenerateSentenceAudioPayload = Field(default_factory=GenerateSentenceAudioPayload)


class GenerateChapterPreviewRequest(JobRequest[GenerateChapterPreviewPayload]):
    job_type: Literal["generate_chapter_preview"]
    payload: GenerateChapterPreviewPayload = Field(default_factory=GenerateChapterPreviewPayload)


class RetryCoverRequest(JobRequest[RetryCoverPayload]):
    job_type: Literal["retry_cover"]
    payload: RetryCoverPayload = Field(default_factory=RetryCoverPayload)


class CreateBackupRequest(JobRequest[CreateBackupPayload]):
    job_type: Literal["create_backup"]
    payload: CreateBackupPayload = Field(default_factory=CreateBackupPayload)


class VerifyBackupRequest(JobRequest[VerifyBackupPayload]):
    job_type: Literal["verify_backup"]


ProcessingJobRequest = Annotated[
    CleanBookRequest
    | CleanAllRequest
    | RefreshBookRequest
    | RefreshAllRequest
    | AudiobookPipelineRequest
    | ImportAudiobookRequest
    | UpgradeImportedAudiobookRequest
    | RebuildImportedAudiobookRequest
    | RematchImportedAudiobookRequest
    | AlignImportedAudiobookRequest
    | MetadataSyncRequest
    | GenerateSentenceAudioRequest
    | GenerateChapterPreviewRequest
    | RetryCoverRequest
    | CreateBackupRequest
    | VerifyBackupRequest,
    Field(discriminator="job_type"),
]
