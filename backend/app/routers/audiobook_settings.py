"""Audiobook provider settings and endpoint health endpoints."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import api_schemas as contracts
from .. import crud
from ..audiobook_schemas import (
    AllEndpointStatsResponse,
    EndpointResponse,
    EndpointStatsResponse,
    SettingsResponse,
    SettingsUpdate,
)
from ..database import get_db
from ..endpoint_types import EndpointConfig, EndpointStats, EndpointUpdate
from ..models import (
    AudiobookSettings,
)
from ..orm_updates import SettingsPatch
from ..services import audiobook_llm
from ..services.endpoint_metrics import endpoint_summaries
from ..services.endpoint_pool import (
    EndpointProbeResult,
    EndpointSettings,
    configured_endpoints,
    probe_endpoints,
)
from ..services.transcription_providers import (
    _transcription_service_health_endpoint,
    transcription_provider_name,
)
from ..services.tts_providers import (
    TTSRequest,
    _synthesize_speech_endpoint,
    tts_provider_name,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _default_endpoint(capability: str) -> EndpointConfig:
    return EndpointConfig(
        id=f"default-{capability}",
        name="Primary",
        provider={"llm": "stub", "tts": "stub", "transcription": "none"}[capability],
    )


def _public_endpoints(settings: AudiobookSettings | None, capability: str) -> list[EndpointResponse]:
    endpoints = configured_endpoints(settings, capability) if settings is not None else [_default_endpoint(capability)]
    return [
        EndpointResponse(
            id=str(endpoint.id or f"{capability}-{index + 1}"),
            name=str(endpoint.name or f"Endpoint {index + 1}"),
            provider=str(endpoint.provider or _default_endpoint(capability).provider),
            api_key_set=bool(endpoint.api_key),
            base_url=endpoint.base_url,
            model=endpoint.model,
            default_voice=endpoint.default_voice,
            language=endpoint.language,
        )
        for index, endpoint in enumerate(endpoints)
    ]


def _settings_response(settings: AudiobookSettings | None) -> SettingsResponse:
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
            tts_max_block_chars=500,
            tts_voice_drift_margin=3.0,
            tts_quality_attempts=3,
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
        tts_max_block_chars=settings.tts_max_block_chars or 500,
        tts_voice_drift_margin=(settings.tts_voice_drift_margin if settings.tts_voice_drift_margin is not None else 3.0),
        tts_quality_attempts=settings.tts_quality_attempts or 3,
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


def _merge_endpoint_secrets(incoming: list[EndpointUpdate], existing: list[EndpointConfig]) -> list[EndpointConfig]:
    existing_by_id = {endpoint.id: endpoint for endpoint in existing}
    merged = []
    for index, endpoint in enumerate(incoming):
        endpoint_id = endpoint.id or f"endpoint-{index + 1}"
        previous = existing_by_id.get(endpoint_id)
        api_key = endpoint.api_key or None
        if "api_key" not in endpoint.model_fields_set and previous is not None and previous.provider == endpoint.provider:
            api_key = previous.api_key
        merged.append(
            EndpointConfig(
                id=endpoint_id,
                name=(endpoint.name or f"Endpoint {index + 1}").strip(),
                provider=endpoint.provider,
                api_key=api_key,
                base_url=endpoint.base_url,
                model=endpoint.model,
                default_voice=endpoint.default_voice,
                language=endpoint.language,
            )
        )
    return merged


def _sync_primary_columns(data: dict[str, object], capability: str, endpoints: list[EndpointConfig]) -> None:
    primary = endpoints[0]
    data[f"{capability}_provider"] = primary.provider
    data[f"{capability}_api_key"] = primary.api_key
    data[f"{capability}_base_url"] = primary.base_url
    data[f"{capability}_model"] = primary.model
    if capability == "tts":
        data["tts_default_voice"] = primary.default_voice
    elif capability == "transcription":
        data["transcription_language"] = primary.language


def _tts_signature(endpoints: list[EndpointConfig]) -> list[tuple[str, str | None, str | None, str | None]]:
    return [(endpoint.provider, endpoint.base_url, endpoint.model, endpoint.default_voice) for endpoint in endpoints]


@router.get("/api/audiobook/settings", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)) -> SettingsResponse:
    settings = await crud.audiobook.get_audiobook_settings(db)
    return _settings_response(settings)


@router.put("/api/audiobook/settings", response_model=SettingsResponse)
async def update_settings(body: SettingsUpdate, db: AsyncSession = Depends(get_db)) -> SettingsResponse:
    data: dict[str, object] = body.model_dump(exclude_unset=True)
    previous = await crud.audiobook.get_audiobook_settings(db)
    previous_tts_endpoints = configured_endpoints(previous, "tts") if previous else []

    next_tts_endpoints = previous_tts_endpoints
    for capability, incoming in (
        ("llm", body.llm_endpoints),
        ("tts", body.tts_endpoints),
        ("transcription", body.transcription_endpoints),
    ):
        field = f"{capability}_endpoints"
        if field not in body.model_fields_set:
            continue
        if incoming is None:
            raise HTTPException(status_code=422, detail=f"{field} must contain at least one endpoint")
        existing = configured_endpoints(previous, capability) if previous else []
        endpoints = _merge_endpoint_secrets(incoming, existing)
        if len({endpoint.id for endpoint in endpoints}) != len(endpoints):
            raise HTTPException(status_code=422, detail=f"{field} endpoint IDs must be unique")
        data[field] = [endpoint.model_dump(mode="json") for endpoint in endpoints]
        _sync_primary_columns(data, capability, endpoints)
        if capability == "tts":
            next_tts_endpoints = endpoints

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
        "tts_max_block_chars": previous.tts_max_block_chars if previous else 500,
        "tts_voice_drift_margin": previous.tts_voice_drift_margin if previous else 3.0,
        "tts_quality_attempts": previous.tts_quality_attempts if previous else 3,
    }
    next_tts = {name: data.get(name, value) for name, value in previous_tts.items()}
    next_tts["tts_provider"] = next_provider
    if "tts_endpoints" in data:
        tts_changed = _tts_signature(previous_tts_endpoints) != _tts_signature(next_tts_endpoints) or next_tts != previous_tts
    else:
        tts_changed = next_tts != previous_tts
    try:
        settings_patch = SettingsPatch.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid audiobook settings update") from exc
    settings = await crud.audiobook.upsert_audiobook_settings(db, settings_patch)
    if tts_changed:
        await crud.audiobook.invalidate_generated_audio_for_tts_change(db)
    return _settings_response(settings)


@router.get("/api/audiobook/settings/llm-stats", response_model=EndpointStatsResponse)
async def get_llm_endpoint_stats(db: AsyncSession = Depends(get_db)) -> EndpointStatsResponse:
    """Compare reliability and response latency across configured LLM endpoints."""
    settings = await crud.audiobook.get_audiobook_settings(db)
    return EndpointStatsResponse(
        endpoints=[EndpointStats.model_validate(item) for item in await endpoint_summaries(db, settings, "llm")]
    )


@router.get("/api/audiobook/settings/endpoint-stats", response_model=AllEndpointStatsResponse)
async def get_endpoint_stats(db: AsyncSession = Depends(get_db)) -> AllEndpointStatsResponse:
    """Compare reliability and response latency across all configured AI endpoints."""
    settings = await crud.audiobook.get_audiobook_settings(db)
    return AllEndpointStatsResponse(
        llm=[EndpointStats.model_validate(item) for item in await endpoint_summaries(db, settings, "llm")],
        tts=[EndpointStats.model_validate(item) for item in await endpoint_summaries(db, settings, "tts")],
        transcription=[EndpointStats.model_validate(item) for item in await endpoint_summaries(db, settings, "transcription")],
    )


ProbeValue = TypeVar("ProbeValue")


def _endpoint_test_results(
    probes: Sequence[EndpointProbeResult[ProbeValue]],
    value_details: Callable[[ProbeValue], contracts.EndpointProbeDetails] | None = None,
) -> list[contracts.EndpointProbe]:
    results: list[contracts.EndpointProbe] = []
    for priority, probe in enumerate(probes, start=1):
        endpoint = probe.endpoint
        result: contracts.EndpointProbe = {
            "endpoint_id": endpoint.id,
            "endpoint": endpoint.name or endpoint.base_url or endpoint.id,
            "priority": priority,
            "provider": endpoint.provider,
            "model": endpoint.model,
            "status": "ready" if probe.success else "error",
            "duration_ms": round(probe.duration_ms, 1),
            "error": probe.error,
        }
        if probe.success and isinstance(probe.value, dict):
            result["response"] = probe.value
        if probe.success and probe.value is not None and value_details is not None:
            details = value_details(probe.value)
            if "audio_bytes" in details:
                result["audio_bytes"] = details["audio_bytes"]
            if "service_status" in details:
                result["service_status"] = details["service_status"]
            if "device" in details:
                result["device"] = details["device"]
            if "loaded_model" in details:
                result["loaded_model"] = details["loaded_model"]
        results.append(result)
    return results


def _optional_probe_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _pool_test_status(results: list[contracts.EndpointProbe]) -> Literal["ready", "partial", "failed"]:
    ready_count = sum(result["status"] == "ready" for result in results)
    if ready_count == len(results) and results:
        return "ready"
    return "partial" if ready_count else "failed"


@router.post("/api/audiobook/settings/test-llm", response_model=contracts.LLMTest)
async def test_llm_settings(db: AsyncSession = Depends(get_db)) -> contracts.LLMTest:
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None:
        return {"status": "ready", "provider": "stub", "model": None, "response": "local harness"}
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }

    async def attempt(endpoint_settings: EndpointSettings) -> dict[str, object]:
        if endpoint_settings.llm_provider == "stub":
            return {"status": "ready", "response": "local harness"}
        raw = await audiobook_llm._call_llm_endpoint(
            endpoint_settings,
            [{"role": "user", "content": "Return JSON with status set to ready."}],
            response_schema=schema,
        )
        parsed = audiobook_llm._extract_json(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError("The LLM test did not return a JSON object.")
        return parsed

    probes = await probe_endpoints(settings, "llm", attempt)
    results = _endpoint_test_results(probes)
    first_ready = next((result for result in results if result["status"] == "ready"), None)
    return {
        "status": _pool_test_status(results),
        "endpoint": first_ready.get("endpoint") if first_ready else None,
        "provider": first_ready.get("provider") if first_ready else None,
        "model": first_ready.get("model") if first_ready else None,
        "response": first_ready.get("response") if first_ready else None,
        "results": results,
    }


@router.post("/api/audiobook/settings/test-tts", response_model=contracts.TTSTest)
async def test_tts_settings(db: AsyncSession = Depends(get_db)) -> contracts.TTSTest:
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None:
        return {"status": "ready", "provider": "stub", "model": None, "audio_bytes": 0}

    async def attempt(endpoint_settings: EndpointSettings) -> bytes:
        audio = await _synthesize_speech_endpoint(
            endpoint_settings,
            TTSRequest(text="Story Manager text to speech is ready."),
        )
        if not audio:
            raise RuntimeError("The TTS provider returned an empty response.")
        return audio

    probes = await probe_endpoints(settings, "tts", attempt)
    results = _endpoint_test_results(probes, value_details=lambda audio: {"audio_bytes": len(audio)})
    first_ready = next((result for result in results if result["status"] == "ready"), None)
    return {
        "status": _pool_test_status(results),
        "endpoint": first_ready.get("endpoint") if first_ready else None,
        "provider": first_ready.get("provider") if first_ready else None,
        "model": first_ready.get("model") if first_ready else None,
        "audio_bytes": first_ready.get("audio_bytes", 0) if first_ready else 0,
        "results": results,
    }


@router.post("/api/audiobook/settings/test-transcription", response_model=contracts.TranscriptionTest)
async def test_transcription_settings(db: AsyncSession = Depends(get_db)) -> contracts.TranscriptionTest:
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None:
        raise HTTPException(status_code=409, detail="Configure a transcription provider first.")
    probes = await probe_endpoints(settings, "transcription", _transcription_service_health_endpoint)
    results = _endpoint_test_results(
        probes,
        value_details=lambda payload: {
            "service_status": _optional_probe_text(payload.get("status")),
            "device": _optional_probe_text(payload.get("device")),
            "loaded_model": _optional_probe_text(payload.get("model")),
        },
    )
    first_ready = next((result for result in results if result["status"] == "ready"), None)
    return {
        "status": _pool_test_status(results),
        "endpoint": first_ready.get("endpoint") if first_ready else None,
        "provider": first_ready.get("provider") if first_ready else None,
        "model": first_ready.get("loaded_model") if first_ready else None,
        "device": first_ready.get("device") if first_ready else None,
        "results": results,
    }
