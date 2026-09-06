"""Atomic update and malformed diagnostic data regression coverage."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.app import models, schemas
from backend.app.lifecycle import PROCESSING_JOB, WEB_IMPORT, InvalidStateTransition, transition_state
from backend.app.logging_config import read_persisted_logs
from backend.app.orm_updates import (
    SettingsPatch,
    CharacterPatch,
    apply_book_patch,
    apply_character_patch,
    apply_cleaning_patch,
    apply_settings_patch,
)


@pytest.mark.parametrize(
    "patch",
    [
        {"name": "Changed", "is_narrator": None},
        {"name": "Changed", "is_narrator": "false"},
        {"name": None},
        {"name": "Changed", "invented_field": 1},
    ],
)
def test_character_patch_validates_all_fields_before_assignment(patch):
    character = models.AudiobookCharacter(name="Original", is_narrator=True)
    with pytest.raises(ValidationError):
        apply_character_patch(character, patch)
    assert (character.name, character.is_narrator) == ("Original", True)
    assert not hasattr(character, "invented_field")


@pytest.mark.parametrize(
    "patch",
    [
        {"llm_model": "changed", "tts_quality_attempts": None},
        {"llm_model": "changed", "tts_max_block_chars": "500"},
        {"llm_model": "changed", "llm_endpoints": [{"provider": False}]},
        {"llm_model": "changed", "invented_setting": 2},
    ],
)
def test_settings_patch_is_atomic_on_invalid_input(patch):
    settings = models.AudiobookSettings(llm_model="Original", llm_api_key="secret")
    with pytest.raises(ValidationError):
        apply_settings_patch(settings, patch)
    assert settings.llm_model == "Original"
    assert settings.llm_api_key == "secret"


def test_settings_patch_preserves_omitted_fields_and_clears_explicit_nullable_fields():
    settings = models.AudiobookSettings(llm_model="Original", llm_api_key="secret", tts_quality_attempts=4)
    apply_settings_patch(settings, {"llm_api_key": None, "llm_endpoints": [{"provider": "ollama"}]})
    assert settings.llm_model == "Original"
    assert settings.llm_api_key is None
    assert settings.tts_quality_attempts == 4
    assert settings.llm_endpoints[0]["provider"] == "ollama"


def test_book_and_cleaning_updates_preserve_omission_and_clear_explicit_fields():
    book = models.Book(title="Original", notes="Notes", series="Series", series_index=2, audiobook_enabled=True)
    apply_book_patch(book, schemas.BookUpdate(notes=None))
    assert (book.title, book.notes, book.audiobook_enabled) == ("Original", None, True)
    apply_book_patch(book, schemas.BookUpdate(series=None))
    assert book.series is None and book.series_index is None
    config = models.CleaningConfig(name="Original", url_pattern="example", content_selectors=[".old"])
    apply_cleaning_patch(config, schemas.CleaningConfigUpdate(content_selectors=None))
    assert (config.name, config.url_pattern, config.content_selectors) == ("Original", "example", None)


@pytest.mark.parametrize(
    "schema,payload",
    [
        (schemas.BookUpdate, {"title": "changed", "audiobook_enabled": None}),
        (schemas.CleaningConfigUpdate, {"name": None}),
        (schemas.CleaningConfigUpdate, {"url_pattern": None}),
    ],
)
def test_nonnullable_update_fields_reject_null(schema, payload):
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_lifecycle_rejects_unsupported_record_field_and_null_status():
    record = SimpleNamespace(status="queued")
    with pytest.raises(TypeError):
        transition_state(record, "typo_status", PROCESSING_JOB, "running")
    assert record.status == "queued" and not hasattr(record, "typo_status")
    nullable = SimpleNamespace(download_status="pending")
    assert transition_state(nullable, "download_status", WEB_IMPORT, None) is None
    assert nullable.download_status is None
    record.status = "pending"
    with pytest.raises(InvalidStateTransition):
        transition_state(record, "status", WEB_IMPORT, None)
    assert record.status == "pending"


def test_log_reader_skips_valid_json_with_invalid_record_shapes_and_redacts(tmp_path):
    path = tmp_path / "logs.jsonl"
    good = {"timestamp": "2026-09-06T00:00:00Z", "level": "INFO", "logger": "test", "message": "api_key=secret"}
    bad = [None, [], 17, "text", {"message": "missing fields"}, {**good, "job_id": True}, {**good, "message": {}}]
    path.write_text("\n".join(json.dumps(row) for row in [*bad, good, {**good, "job_id": 4}]))
    entries = read_persisted_logs(log_file=path, level="INFO")
    assert len(entries) == 2
    assert entries[1]["job_id"] == 4
    assert all("secret" not in row["message"] and "[REDACTED]" in row["message"] for row in entries)


@pytest.mark.parametrize("kind", ["settings", "character"])
def test_copied_patch_instances_are_revalidated_before_assignment(kind):
    if kind == "settings":
        record = models.AudiobookSettings(llm_model="original", tts_quality_attempts=3)
        patch = SettingsPatch(llm_model="changed").model_copy(update={"tts_quality_attempts": None})
        with pytest.raises(ValidationError):
            apply_settings_patch(record, patch)
        assert (record.llm_model, record.tts_quality_attempts) == ("original", 3)
    else:
        record = models.AudiobookCharacter(name="original", is_narrator=True)
        patch = CharacterPatch(name="changed").model_copy(update={"is_narrator": None})
        with pytest.raises(ValidationError):
            apply_character_patch(record, patch)
        assert (record.name, record.is_narrator) == ("original", True)
