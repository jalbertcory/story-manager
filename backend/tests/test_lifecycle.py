"""Tests for centralized lifecycle definitions and transition enforcement."""

from dataclasses import dataclass

import pytest

from backend.app.lifecycle import (
    LIFECYCLES,
    PROCESSING_JOB,
    InvalidStateTransition,
    ProcessingJobStatus,
    lifecycle_manifest,
    transition_state,
)


@dataclass
class Record:
    status: str | None


def test_every_lifecycle_definition_is_internally_consistent():
    manifest = lifecycle_manifest()

    assert manifest.keys() == LIFECYCLES.keys()
    for key, machine in LIFECYCLES.items():
        assert set(machine.labels) == machine.states, key
        assert set(machine.transitions) == machine.states, key
        assert machine.active_states <= machine.states, key
        assert machine.terminal_states <= machine.states, key
        assert machine.failure_states <= machine.states, key
        assert machine.retryable_states <= machine.states, key
        assert set(machine.recovery) == machine.active_states, key
        assert all(target in machine.states for targets in machine.transitions.values() for target in targets), key
        assert all(target in machine.states or isinstance(target, str) for target in machine.recovery.values()), key
        assert {item["value"] for item in manifest[key]["states"]} == machine.states


def test_transition_helper_assigns_valid_state():
    record = Record(status=ProcessingJobStatus.QUEUED.value)

    value = transition_state(record, "status", PROCESSING_JOB, ProcessingJobStatus.RUNNING)

    assert value == ProcessingJobStatus.RUNNING.value
    assert record.status == ProcessingJobStatus.RUNNING.value


def test_invalid_transition_explains_context_and_allowed_targets():
    record = Record(status=ProcessingJobStatus.COMPLETED.value)

    with pytest.raises(InvalidStateTransition) as error:
        transition_state(
            record,
            "status",
            PROCESSING_JOB,
            ProcessingJobStatus.RUNNING,
            context="job 42",
        )

    assert "job 42" in str(error.value)
    assert "'completed' -> 'running'" in str(error.value)
    assert "Allowed next states: none" in str(error.value)
    assert record.status == ProcessingJobStatus.COMPLETED.value


def test_unknown_persisted_state_is_actionable():
    record = Record(status="mystery")

    with pytest.raises(InvalidStateTransition, match="Unknown processing job state 'mystery'"):
        transition_state(record, "status", PROCESSING_JOB, ProcessingJobStatus.ERROR)


@pytest.mark.asyncio
async def test_lifecycle_manifest_endpoint(app_client):
    response = app_client.get("/api/lifecycles")

    assert response.status_code == 200
    body = response.json()
    assert body["processing_job"]["groups"]["running"] == ["running"]
    assert body["sentence"]["groups"]["audio_in_progress"] == [
        "audio_queued",
        "audio_generating",
    ]
