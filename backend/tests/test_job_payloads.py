"""Payload validation protects every entry point to the durable job ledger."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select

from backend.app import crud
from backend.app.job_payloads import (
    AudiobookPipelinePayload,
    ImportAudiobookPayload,
    JOB_PAYLOAD_MODELS,
    ProcessingJobRequest,
    validate_job_payload,
)
from backend.app.models import ProcessingJob
from backend.app.services.processing_queue import JOB_POLICIES, ProcessingQueue, queue_processing_job

VALID_PAYLOADS = {
    "clean_book": {},
    "clean_all": {"reason": "Cleaning rules changed"},
    "refresh_book": {},
    "refresh_all": {"trigger": "scheduled"},
    "import_web_book": {"source_url": "https://example.com/story"},
    "audiobook_pipeline": {"mode": "reconcile"},
    "import_audiobook": {"auto_align": False},
    "upgrade_imported_audiobook": {"format_version": 2},
    "rebuild_imported_audiobook": {"pipeline_version": 2, "force": True},
    "rematch_imported_audiobook": {"realign": True},
    "align_imported_audiobook": {},
    "metadata_sync": {"metadata_job_id": 12, "trigger": "manual"},
    "generate_sentence_audio": {},
    "generate_chapter_preview": {},
    "retry_cover": {},
    "create_backup": {},
    "verify_backup": {"filename": "test.story-manager.zip"},
}


def test_every_worker_policy_has_a_payload_contract():
    assert JOB_POLICIES.keys() == JOB_PAYLOAD_MODELS.keys() == VALID_PAYLOADS.keys()


@pytest.mark.parametrize("job_type,payload", VALID_PAYLOADS.items())
def test_known_payloads_round_trip_without_changing_stored_fields(job_type, payload):
    model = validate_job_payload(job_type, payload)
    assert model.model_dump(mode="json", exclude_unset=True) == payload
    with pytest.raises(ValidationError):
        validate_job_payload(job_type, {**payload, "unexpected_field": True})


@pytest.mark.parametrize("mode", ["resume", "reconcile", "rebuild", "audio", "roster", "step", "batch"])
def test_supported_pipeline_modes(mode):
    assert AudiobookPipelinePayload(mode=mode).mode == mode


def test_legacy_missing_defaults_keep_worker_semantics():
    assert validate_job_payload("audiobook_pipeline", None).model_dump() == {"mode": "resume"}
    assert validate_job_payload("import_audiobook", {}).model_dump() == {"auto_align": True}
    assert validate_job_payload("rematch_imported_audiobook", {}).model_dump() == {"realign": False}
    assert validate_job_payload("refresh_all", {}).model_dump() == {"trigger": "manual"}
    assert validate_job_payload("metadata_sync", {}).model_dump()["metadata_job_id"] is None


INVALID_PAYLOADS = [
    ("clean_book", {"mode": "rebuild"}),
    ("audiobook_pipeline", {"mode": "typo"}),
    ("audiobook_pipeline", {"mode": None}),
    ("import_audiobook", {"auto_align": "false"}),
    ("import_audiobook", {"auto_align": 0}),
    ("rematch_imported_audiobook", {"realign": "yes"}),
    ("metadata_sync", {"metadata_job_id": True}),
    ("metadata_sync", {"metadata_job_id": -1}),
    ("upgrade_imported_audiobook", {"format_version": "2"}),
    ("rebuild_imported_audiobook", {"force": "false"}),
    ("refresh_all", {"trigger": 3}),
    ("verify_backup", {}),
    ("verify_backup", {"filename": ""}),
    ("verify_backup", {"filename": 12}),
]


@pytest.mark.parametrize("job_type,payload", INVALID_PAYLOADS)
@pytest.mark.asyncio
async def test_http_rejects_invalid_combinations_without_queuing(app_client, sqlite_sessionmaker, job_type, payload):
    response = app_client.post(
        "/api/processing/jobs", json={"job_type": job_type, "book_ids": [1], "target_id": 1, "payload": payload}
    )
    assert response.status_code == 422
    assert any("payload" in error["loc"] for error in response.json()["detail"])
    async with sqlite_sessionmaker() as db:
        assert await db.scalar(select(func.count(ProcessingJob.id))) == 0


@pytest.mark.asyncio
async def test_persistence_validates_before_deduplication(sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        await crud.create_processing_job(db, job_type="clean_book", dedupe_key="existing")
        with pytest.raises(ValidationError):
            await crud.create_processing_job(db, job_type="clean_book", payload={"mode": "audio"}, dedupe_key="existing")
        assert await db.scalar(select(func.count(ProcessingJob.id))) == 1


@pytest.mark.asyncio
async def test_internal_producers_cannot_mix_job_type_and_payload(sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        with pytest.raises(ValueError, match="requires CleanBookPayload"):
            await queue_processing_job(db=db, job_type="clean_book", payload=ImportAudiobookPayload())
        assert await db.scalar(select(func.count(ProcessingJob.id))) == 0


@pytest.mark.asyncio
async def test_invalid_legacy_rows_remain_visible_but_cannot_be_retried(app_client, sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        # Bypass today's ingress validation to represent a pre-existing row.
        job = ProcessingJob(job_type="audiobook_pipeline", payload={"mode": "typo"}, status="error")
        db.add(job)
        await db.commit()
        job_id = job.id
    response = app_client.get(f"/api/processing/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["payload"] == {"mode": "typo"}
    assert app_client.post(f"/api/processing/jobs/{job_id}/retry").status_code == 422
    async with sqlite_sessionmaker() as db:
        assert (await db.get(ProcessingJob, job_id)).status == "error"


@pytest.mark.asyncio
async def test_worker_rejects_invalid_legacy_payload_before_side_effects(monkeypatch):
    queue = ProcessingQueue()
    execute = AsyncMock()
    monkeypatch.setattr(queue, "_run_audiobook_pipeline", execute)
    with pytest.raises(ValidationError):
        await queue._execute(SimpleNamespace(job_type="audiobook_pipeline", payload={"mode": "typo"}))
    execute.assert_not_awaited()


def test_http_contract_discriminates_payloads_by_job_type():
    schema = TypeAdapter(ProcessingJobRequest).json_schema()
    assert schema["discriminator"]["propertyName"] == "job_type"
    assert set(schema["discriminator"]["mapping"]) == VALID_PAYLOADS.keys() - {"import_web_book"}


@pytest.mark.asyncio
async def test_typed_payload_is_serialized_as_json_in_the_ledger(sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        job = await queue_processing_job(db=db, job_type="import_audiobook", payload=ImportAudiobookPayload(auto_align=False))
        assert job.payload == {"auto_align": False}
        assert validate_job_payload(job.job_type, job.payload).auto_align is False


@pytest.mark.asyncio
async def test_backup_verification_payload_identifies_the_job(app_client):
    for filename in ["first.story-manager.zip", "second.story-manager.zip"]:
        response = app_client.post(
            "/api/processing/jobs",
            json={
                "job_type": "verify_backup",
                "payload": {"filename": filename},
            },
        )
        assert response.status_code == 202
        assert response.json()["jobs"][0]["payload"] == {"filename": filename}
    jobs = app_client.get("/api/processing/jobs").json()
    assert len(jobs) == 2
