"""Qwen3-TTS adapter with preset, cloned, designed, and LoRA voices."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import gc
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
import threading
from typing import TYPE_CHECKING, Protocol, TypedDict, cast

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
import torch

from services.omnivoice.audio_quality import AudioQualityError, validate_generated_audio
from services.speaker_similarity import get_speaker_verifier
from services.tts_consistency import seed_for_attempt, voice_instruction
from .voice_store import StoredVoice, VoiceStore

if TYPE_CHECKING:
    from qwen_tts import Qwen3TTSModel
    from qwen_tts.inference.qwen3_tts_model import VoiceClonePromptItem

logger = logging.getLogger(__name__)
DEVICE = os.getenv("QWEN3_TTS_DEVICE", "auto")
LANGUAGE = os.getenv("QWEN3_TTS_LANGUAGE", "English")
CUSTOM_MODEL = os.getenv("QWEN3_CUSTOM_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
DESIGN_MODEL = os.getenv("QWEN3_DESIGN_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
CLONE_MODEL = os.getenv("QWEN3_CLONE_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
VOICE_STORE_PATH = Path(os.getenv("QWEN3_VOICE_STORE", ".cache/qwen3-tts/voices"))
LORA_ROOT = Path(os.getenv("QWEN3_LORA_ROOT", ".cache/qwen3-tts/lora"))
MP3_BITRATE = os.getenv("QWEN3_MP3_BITRATE", "128k")
DESIGN_TEXT = os.getenv(
    "QWEN3_VOICE_DESIGN_TEXT",
    "Once upon a quiet morning, I found the courage to tell this story clearly, warmly, and in my own voice.",
)
_SAFE_ADAPTER_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class GenerateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    voice: str | None = None
    voice_id: str | None = None
    language: str | None = None
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    min_voice_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)
    quality_attempts: int = Field(default=3, ge=1, le=10)


class DesignVoiceRequest(BaseModel):
    voice: str = Field(min_length=1, max_length=1000)
    language: str | None = None
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    avoid_voice_ids: list[str] = Field(default_factory=list, max_length=32)
    max_voice_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)
    quality_attempts: int = Field(default=6, ge=1, le=20)


class DesignVoiceResponse(BaseModel):
    id: str
    voice: str
    sample_text: str
    sample_url: str
    max_cross_voice_similarity: float | None = None
    attempts: int = 1


class PresetVoiceRequest(BaseModel):
    voice_id: str = Field(pattern=r"^preset:[A-Za-z0-9_]+$")
    voice: str = Field(min_length=1, max_length=1000)
    language: str | None = None
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    avoid_voice_ids: list[str] = Field(default_factory=list, max_length=32)
    max_voice_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)


class BatchGenerateRequest(BaseModel):
    requests: list[GenerateRequest] = Field(min_length=1, max_length=16)


class BatchGenerateItem(BaseModel):
    audio_base64: str
    duration_ms: int
    voice_similarity: float | None = None
    attempts: int = 1


class BatchGenerateResponse(BaseModel):
    items: list[BatchGenerateItem]


def _encode_mp3(audio: np.ndarray, sampling_rate: int) -> tuple[bytes, int]:
    from pydub import AudioSegment

    pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    segment = AudioSegment(pcm.tobytes(), frame_rate=sampling_rate, sample_width=2, channels=1)
    output = BytesIO()
    segment.export(output, format="mp3", bitrate=MP3_BITRATE)
    return output.getvalue(), len(segment)


def _instruction(profile: str | None) -> str:
    return voice_instruction(profile)


class TTSRuntime(Protocol):
    """Interface shared by the PyTorch and MLX HTTP adapters."""

    device: str
    _model_kind: str | None
    _voices: VoiceStore

    def load(self) -> None: ...

    def generate(self, request: GenerateRequest) -> tuple[bytes, int, float | None, int]: ...

    def generate_batch(self, requests: list[GenerateRequest]) -> list[tuple[bytes, int, float | None, int]]: ...

    def design(self, request: DesignVoiceRequest) -> tuple[StoredVoice, float | None, int]: ...

    def materialize_preset(self, request: PresetVoiceRequest) -> tuple[StoredVoice, float | None, int]: ...


class LoRAMetadata(TypedDict):
    ref_audio: str
    ref_audio_path: str
    ref_text: str


class QwenRuntime:
    def __init__(self) -> None:
        self.device = "unloaded"
        self._model_kind: str | None = None
        self._model: Qwen3TTSModel | None = None
        self._adapter_name: str | None = None
        self._lock = threading.RLock()
        self._voices = VoiceStore(VOICE_STORE_PATH)
        self._clone_prompts: dict[str, list[VoiceClonePromptItem]] = {}

    def load(self) -> None:
        self.device = self._resolve_device()
        logger.info("Qwen3-TTS adapter ready; models will load lazily on %s.", self.device)

    @staticmethod
    def _resolve_device() -> str:
        if DEVICE != "auto":
            return DEVICE
        if torch.cuda.is_available():
            return "cuda:0"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _load(self, kind: str, adapter_name: str | None = None) -> Qwen3TTSModel:
        if self._model is not None and self._model_kind == kind and self._adapter_name == adapter_name:
            return self._model
        from qwen_tts import Qwen3TTSModel

        self._model = None
        self._clone_prompts.clear()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        model_id = {"custom": CUSTOM_MODEL, "design": DESIGN_MODEL, "clone": CLONE_MODEL, "lora": CLONE_MODEL}[kind]
        dtype = torch.bfloat16 if self.device.startswith("cuda") else torch.float32
        kwargs = {"dtype": dtype}
        if self.device != "cpu":
            kwargs["device_map"] = self.device
        model = Qwen3TTSModel.from_pretrained(model_id, **kwargs)
        self._model = model
        if kind == "lora":
            adapter_path, _metadata = self._lora_metadata(adapter_name or "")
            from peft import PeftModel

            model.model.talker = PeftModel.from_pretrained(model.model.talker, adapter_path)
            model.model.talker.eval()
        self._model_kind = kind
        self._adapter_name = adapter_name
        return model

    def _lora_metadata(self, name: str) -> tuple[Path, LoRAMetadata]:
        if not _SAFE_ADAPTER_RE.fullmatch(name):
            raise KeyError(f"Invalid LoRA adapter name: {name!r}")
        path = (LORA_ROOT / name).resolve()
        if not path.is_relative_to(LORA_ROOT.resolve()) or not path.is_dir():
            raise KeyError(f"Unknown LoRA adapter: {name}")
        metadata = json.loads((path / "voice.json").read_text(encoding="utf-8"))
        if (
            not isinstance(metadata, dict)
            or not isinstance(metadata.get("ref_audio"), str)
            or not isinstance(metadata.get("ref_text"), str)
        ):
            raise ValueError(f"LoRA adapter {name} has invalid voice.json reference metadata.")
        reference = (path / str(metadata["ref_audio"])).resolve()
        if not reference.is_relative_to(path) or not reference.is_file() or not metadata.get("ref_text"):
            raise ValueError(f"LoRA adapter {name} has invalid voice.json reference metadata.")
        metadata["ref_audio_path"] = str(reference)
        # The reference fields above are validated; preserve any extra model metadata.
        return path, cast(LoRAMetadata, metadata)

    def _clone_prompt(self, voice_id: str) -> list[VoiceClonePromptItem]:
        cached = self._clone_prompts.get(voice_id)
        if cached is not None:
            return cached
        if self._model is None:
            raise RuntimeError("Qwen3-TTS model is not loaded")
        if voice_id.startswith("lora:"):
            _path, metadata = self._lora_metadata(voice_id.removeprefix("lora:"))
            prompt = self._model.create_voice_clone_prompt(
                ref_audio=metadata["ref_audio_path"],
                ref_text=metadata["ref_text"],
                x_vector_only_mode=True,
            )
        else:
            stored = self._voices.get(voice_id)
            prompt = self._model.create_voice_clone_prompt(
                ref_audio=str(self._voices.sample_path(voice_id)), ref_text=stored.ref_text
            )
        self._clone_prompts[voice_id] = prompt
        # Qwen returns these records; the isolated runtime has no root typing metadata.
        return cast(list[VoiceClonePromptItem], prompt)

    def _reference_path(self, voice_id: str) -> Path | None:
        if voice_id.startswith("preset:"):
            return None
        if voice_id.startswith("lora:"):
            _path, metadata = self._lora_metadata(voice_id.removeprefix("lora:"))
            return Path(metadata["ref_audio_path"])
        return self._voices.sample_path(voice_id)

    def _cross_voice_similarity(
        self,
        request: DesignVoiceRequest | PresetVoiceRequest,
        audio: np.ndarray,
        rate: int,
    ) -> float | None:
        scores = []
        verifier = get_speaker_verifier()
        for voice_id in dict.fromkeys(request.avoid_voice_ids):
            reference = self._reference_path(voice_id)
            if reference is None:
                continue
            similarity = verifier.similarity(f"voice-roster:{voice_id}", reference, audio, rate)
            if similarity is not None:
                scores.append(similarity)
        return max(scores, default=None)

    def _generate_once(self, request: GenerateRequest) -> tuple[np.ndarray, int]:
        if request.seed is not None:
            torch.manual_seed(request.seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(request.seed)
        language = request.language or LANGUAGE
        voice_id = request.voice_id or "preset:Ryan"
        if voice_id.startswith("preset:"):
            model = self._load("custom")
            wavs, rate = model.generate_custom_voice(
                text=request.text,
                language=language,
                speaker=voice_id.removeprefix("preset:"),
                instruct=_instruction(request.voice),
                non_streaming_mode=True,
            )
        else:
            kind = "lora" if voice_id.startswith("lora:") else "clone"
            adapter = voice_id.removeprefix("lora:") if kind == "lora" else None
            model = self._load(kind, adapter)
            generation_options = {}
            if kind == "lora" and (instruct := _instruction(request.voice)):
                formatted = f"<|im_start|>user\n{instruct}<|im_end|>\n"
                generation_options["instruct_ids"] = model._tokenize_texts([formatted])
            wavs, rate = model.generate_voice_clone(
                text=request.text,
                language=language,
                voice_clone_prompt=self._clone_prompt(voice_id),
                non_streaming_mode=True,
                **generation_options,
            )
        return np.concatenate(wavs) if len(wavs) > 1 else wavs[0], rate

    def _generate_many_once(self, requests: list[GenerateRequest]) -> tuple[list[np.ndarray], int]:
        """Generate a compatible request group through Qwen's native list API."""
        if not requests:
            return [], 0
        first = requests[0]
        if first.seed is not None:
            torch.manual_seed(first.seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(first.seed)
        languages = [request.language or LANGUAGE for request in requests]
        voice_ids = [request.voice_id or "preset:Ryan" for request in requests]
        if voice_ids[0].startswith("preset:"):
            model = self._load("custom")
            wavs, rate = model.generate_custom_voice(
                text=[request.text for request in requests],
                language=languages,
                speaker=[voice_id.removeprefix("preset:") for voice_id in voice_ids],
                instruct=[_instruction(request.voice) for request in requests],
                non_streaming_mode=True,
            )
        else:
            voice_id = voice_ids[0]
            kind = "lora" if voice_id.startswith("lora:") else "clone"
            adapter = voice_id.removeprefix("lora:") if kind == "lora" else None
            model = self._load(kind, adapter)
            generation_options = {}
            if kind == "lora":
                formatted = [f"<|im_start|>user\n{_instruction(request.voice)}<|im_end|>\n" for request in requests]
                generation_options["instruct_ids"] = model._tokenize_texts(formatted)
            wavs, rate = model.generate_voice_clone(
                text=[request.text for request in requests],
                language=languages,
                voice_clone_prompt=self._clone_prompt(voice_id),
                non_streaming_mode=True,
                **generation_options,
            )
        if len(wavs) != len(requests):
            raise RuntimeError(f"Qwen returned {len(wavs)} outputs for {len(requests)} batch requests.")
        return [np.asarray(wav).reshape(-1) for wav in wavs], rate

    def _validate_audio(
        self,
        request: GenerateRequest,
        audio: np.ndarray,
        rate: int,
    ) -> float | None:
        validate_generated_audio(audio, rate)
        similarity = None
        reference = self._reference_path(request.voice_id) if request.voice_id else None
        if reference is not None:
            similarity = get_speaker_verifier().similarity(request.voice_id or "", reference, audio, rate)
        if request.min_voice_similarity is not None and similarity is not None and similarity < request.min_voice_similarity:
            raise AudioQualityError(f"speaker similarity {similarity:.3f} is below {request.min_voice_similarity:.3f}")
        return similarity

    def _generate_valid_audio(
        self,
        request: GenerateRequest,
        *,
        start_attempt: int = 1,
    ) -> tuple[np.ndarray, int, float | None, int]:
        last_error = None
        for attempt in range(start_attempt, request.quality_attempts + 1):
            attempt_request = request
            if request.seed is not None:
                attempt_request = request.model_copy(update={"seed": seed_for_attempt(request.seed, attempt)})
            audio, rate = self._generate_once(attempt_request)
            try:
                similarity = self._validate_audio(request, audio, rate)
                return audio, rate, similarity, attempt
            except AudioQualityError as exc:
                last_error = exc
                logger.warning(
                    "Rejected Qwen3-TTS output on attempt %d/%d: %s",
                    attempt,
                    request.quality_attempts,
                    exc,
                )
        raise AudioQualityError(f"Qwen3-TTS failed quality validation: {last_error}") from last_error

    def generate(self, request: GenerateRequest) -> tuple[bytes, int, float | None, int]:
        with self._lock:
            audio, rate, similarity, attempts = self._generate_valid_audio(request)
            encoded, duration = _encode_mp3(audio, rate)
            return encoded, duration, similarity, attempts

    def generate_batch(self, requests: list[GenerateRequest]) -> list[tuple[bytes, int, float | None, int]]:
        """Batch compatible voices natively while retaining per-item validation and retries."""
        with self._lock:
            generated: list[tuple[np.ndarray, int, float | None, int] | None] = [None] * len(requests)
            groups: dict[tuple[str, int | None], list[int]] = {}
            for index, request in enumerate(requests):
                voice_id = request.voice_id or "preset:Ryan"
                # Clone batches require one shared prompt. A shared seed is also
                # required because torch has one generator for the native batch.
                key = (voice_id, request.seed)
                groups.setdefault(key, []).append(index)

            for indices in groups.values():
                group = [requests[index] for index in indices]
                if len(group) == 1:
                    generated[indices[0]] = self._generate_valid_audio(group[0])
                    continue
                audios, rate = self._generate_many_once(group)
                for index, request, audio in zip(indices, group, audios, strict=True):
                    try:
                        similarity = self._validate_audio(request, audio, rate)
                        generated[index] = (audio, rate, similarity, 1)
                    except AudioQualityError as exc:
                        logger.warning(
                            "Rejected native Qwen batch output for request %d; retrying individually: %s",
                            index + 1,
                            exc,
                        )
                        generated[index] = self._generate_valid_audio(request, start_attempt=2)

            results = []
            for item in generated:
                if item is None:
                    raise RuntimeError("Qwen batch generation did not produce every requested item.")
                audio, rate, similarity, attempts = item
                encoded, duration = _encode_mp3(audio, rate)
                results.append((encoded, duration, similarity, attempts))
            return results

    def design(self, request: DesignVoiceRequest) -> tuple[StoredVoice, float | None, int]:
        with self._lock:
            model = self._load("design")
            last_similarity = None
            for attempt in range(1, request.quality_attempts + 1):
                attempt_seed = seed_for_attempt(request.seed, attempt)
                if attempt_seed is not None:
                    torch.manual_seed(attempt_seed)
                    if torch.cuda.is_available():
                        torch.cuda.manual_seed_all(attempt_seed)
                wavs, rate = model.generate_voice_design(
                    text=DESIGN_TEXT,
                    language=request.language or LANGUAGE,
                    instruct=_instruction(request.voice),
                    non_streaming_mode=True,
                )
                audio = np.concatenate(wavs) if len(wavs) > 1 else wavs[0]
                validate_generated_audio(audio, rate)
                last_similarity = self._cross_voice_similarity(request, audio, rate)
                if (
                    request.max_voice_similarity is None
                    or last_similarity is None
                    or last_similarity <= request.max_voice_similarity
                ):
                    stored = self._voices.create(request.voice, DESIGN_TEXT, audio, rate)
                    return stored, last_similarity, attempt
                logger.warning(
                    "Rejected designed voice on attempt %d/%d: cross-character similarity %.3f exceeds %.3f",
                    attempt,
                    request.quality_attempts,
                    last_similarity,
                    request.max_voice_similarity,
                )
        raise AudioQualityError(
            "Qwen3-TTS could not design a sufficiently distinct voice "
            f"(closest roster similarity {last_similarity:.3f}, limit {request.max_voice_similarity:.3f})."
        )

    def materialize_preset(self, request: PresetVoiceRequest) -> tuple[StoredVoice, float | None, int]:
        """Render an official preset once and persist it as a clone reference."""
        with self._lock:
            audio, rate = self._generate_once(
                GenerateRequest(
                    text=DESIGN_TEXT,
                    voice=request.voice,
                    voice_id=request.voice_id,
                    language=request.language,
                    seed=request.seed,
                    quality_attempts=1,
                )
            )
            validate_generated_audio(audio, rate)
            similarity = self._cross_voice_similarity(request, audio, rate)
            if (
                request.max_voice_similarity is not None
                and similarity is not None
                and similarity > request.max_voice_similarity
            ):
                raise AudioQualityError(
                    f"preset {request.voice_id} is too similar to the existing cast "
                    f"({similarity:.3f}, limit {request.max_voice_similarity:.3f})."
                )
            description = f"Official Qwen preset {request.voice_id.removeprefix('preset:')}: {request.voice}"
            return self._voices.create(description, DESIGN_TEXT, audio, rate), similarity, 1


runtime: TTSRuntime = QwenRuntime()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    runtime.load()
    yield


app = FastAPI(title="Story Manager Qwen3-TTS Adapter", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ready",
        "device": runtime.device,
        "loaded_model": runtime._model_kind,
        "voice_store": str(VOICE_STORE_PATH),
        "lora_root": str(LORA_ROOT),
    }


@app.post("/voices/design", response_model=DesignVoiceResponse)
async def design_voice(request: DesignVoiceRequest) -> DesignVoiceResponse:
    try:
        stored, max_similarity, attempts = await asyncio.to_thread(runtime.design, request)
    except AudioQualityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Qwen3 voice design failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return DesignVoiceResponse(
        id=stored.id,
        voice=stored.description,
        sample_text=stored.ref_text,
        sample_url=f"/voices/{stored.id}/sample",
        max_cross_voice_similarity=max_similarity,
        attempts=attempts,
    )


@app.post("/voices/from-preset", response_model=DesignVoiceResponse)
async def materialize_preset_voice(request: PresetVoiceRequest) -> DesignVoiceResponse:
    try:
        stored, max_similarity, attempts = await asyncio.to_thread(runtime.materialize_preset, request)
    except AudioQualityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Qwen3 preset materialization failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return DesignVoiceResponse(
        id=stored.id,
        voice=stored.description,
        sample_text=stored.ref_text,
        sample_url=f"/voices/{stored.id}/sample",
        max_cross_voice_similarity=max_similarity,
        attempts=attempts,
    )


@app.get("/voices/{voice_id}/sample")
async def voice_sample(voice_id: str) -> Response:
    if voice_id.startswith(("preset:", "lora:")):
        try:
            audio, _duration, _similarity, _attempts = await asyncio.to_thread(
                runtime.generate,
                GenerateRequest(text=DESIGN_TEXT, voice_id=voice_id, quality_attempts=1),
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Qwen3 voice sample generation failed.")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return Response(audio, media_type="audio/mpeg")
    try:
        path = runtime._voices.sample_path(voice_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="audio/wav", filename=f"{voice_id}.wav")


@app.post("/generate")
async def generate(request: GenerateRequest) -> Response:
    try:
        audio, duration, similarity, attempts = await asyncio.to_thread(runtime.generate, request)
    except Exception as exc:
        logger.exception("Qwen3 generation failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(
        audio,
        media_type="audio/mpeg",
        headers={
            "X-Audio-Duration-Ms": str(duration),
            "X-Generation-Attempts": str(attempts),
            **({"X-Voice-Similarity": f"{similarity:.6f}"} if similarity is not None else {}),
        },
    )


@app.post("/generate-batch", response_model=BatchGenerateResponse)
async def generate_batch(request: BatchGenerateRequest) -> BatchGenerateResponse:
    try:
        generated = await asyncio.to_thread(runtime.generate_batch, request.requests)
    except Exception as exc:
        logger.exception("Qwen3 batch generation failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return BatchGenerateResponse(
        items=[
            BatchGenerateItem(
                audio_base64=base64.b64encode(audio).decode("ascii"),
                duration_ms=duration,
                voice_similarity=similarity,
                attempts=attempts,
            )
            for audio, duration, similarity, attempts in generated
        ]
    )
