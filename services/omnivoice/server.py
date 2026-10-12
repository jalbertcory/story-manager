"""FastAPI adapter exposing official OmniVoice through Story Manager's API."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from io import BytesIO
import logging
import os
from pathlib import Path
import threading
from typing import cast

# Let unsupported MPS operations fall back to CPU rather than terminating a
# long audiobook run. This must be set before importing torch.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import numpy as np  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from omnivoice import OmniVoice  # noqa: E402
from omnivoice.utils.common import get_best_device  # noqa: E402
from omnivoice.utils.text import normalize_text  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from pydub import AudioSegment  # noqa: E402
import torch  # noqa: E402

from .audio_quality import validate_generated_audio  # noqa: E402
from .normalization import prepare_for_normalization  # noqa: E402
from .prompt import translate_generation_prompt  # noqa: E402
from .voice_store import StoredVoice, VoiceStore  # noqa: E402
from services.tts_consistency import seed_for_attempt  # noqa: E402
from services.voice_roster import SpeakerCheck, SpeakerGuard, generate_checked  # noqa: E402

logger = logging.getLogger(__name__)

MODEL_ID = os.getenv("OMNIVOICE_MODEL", "k2-fsa/OmniVoice")
DEVICE = os.getenv("OMNIVOICE_DEVICE", "auto")
NUM_STEPS = int(os.getenv("OMNIVOICE_NUM_STEPS", "16"))
MP3_BITRATE = os.getenv("OMNIVOICE_MP3_BITRATE", "96k")
MAX_BATCH_SIZE = max(1, int(os.getenv("OMNIVOICE_MAX_BATCH_SIZE", "8")))
NATIVE_BATCHING = os.getenv("OMNIVOICE_NATIVE_BATCHING", "false").lower() in {"1", "true", "yes"}
NORMALIZE_TEXT = os.getenv("OMNIVOICE_NORMALIZE_TEXT", "true").lower() not in {"0", "false", "no"}
QUALITY_ATTEMPTS = max(1, int(os.getenv("OMNIVOICE_QUALITY_ATTEMPTS", "3")))
VOICE_STORE_PATH = Path(
    os.getenv(
        "OMNIVOICE_VOICE_STORE",
        str(Path(os.getenv("HF_HOME", ".cache/omnivoice")) / "voices"),
    )
)
VOICE_DESIGN_TEXT = os.getenv(
    "OMNIVOICE_VOICE_DESIGN_TEXT",
    "Once upon a quiet morning, I found the courage to tell this story clearly, warmly, and in my own voice.",
)


class GenerateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str | None = None
    voice_id: str | None = None
    language: str | None = None
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    # Legacy absolute speaker-similarity floor; prefer drift_margin.
    min_voice_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)
    # Standard deviations below the voice's calibrated similarity before a take
    # is retried; 0 or null disables the drift and cast checks.
    drift_margin: float | None = Field(default=None, ge=0.0, le=10.0)
    cast_voice_ids: list[str] = Field(default_factory=list, max_length=64)
    quality_attempts: int = Field(default=QUALITY_ATTEMPTS, ge=1, le=10)


class DesignVoiceRequest(BaseModel):
    voice: str = Field(min_length=1, max_length=1000)
    language: str | None = None


class DesignVoiceResponse(BaseModel):
    id: str
    voice: str
    sample_text: str
    sample_url: str


class BatchGenerateRequest(BaseModel):
    requests: list[GenerateRequest] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class BatchGenerateItem(BaseModel):
    audio_base64: str
    duration_ms: int
    voice_similarity: float | None = None
    attempts: int = 1


class BatchGenerateResponse(BaseModel):
    items: list[BatchGenerateItem]


def _encode_audio(audio: np.ndarray, sampling_rate: int) -> tuple[bytes, int]:
    pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    segment = AudioSegment(
        pcm.tobytes(),
        frame_rate=sampling_rate,
        sample_width=2,
        channels=1,
    )
    output = BytesIO()
    segment.export(output, format="mp3", bitrate=MP3_BITRATE)
    return output.getvalue(), len(segment)


def _text_normalization_available() -> bool:
    """Load OmniVoice's optional normalizer now rather than on the first sentence."""
    try:
        normalize_text("1", "en")
    except ImportError:
        logger.warning(
            "OMNIVOICE_NORMALIZE_TEXT is enabled but WeTextProcessing is not installed; "
            "numbers, dates, and currency will be passed to OmniVoice unnormalized."
        )
        return False
    return True


class OmniVoiceRuntime:
    def __init__(self) -> None:
        self.model: OmniVoice | None = None
        self.device = "unloaded"
        self._generate_lock = threading.RLock()
        self._voice_store = VoiceStore(VOICE_STORE_PATH)
        self._voice_clone_prompts: dict[str, object] = {}
        self.normalize_text = False
        self._speaker_guard = SpeakerGuard(self._voice_store.sample_path, self._generate_probe)

    def load(self) -> None:
        self.device = get_best_device() if DEVICE == "auto" else DEVICE
        dtype = torch.float32 if self.device == "cpu" else torch.float16
        logger.info("Loading %s on %s (%s).", MODEL_ID, self.device, dtype)
        self.model = OmniVoice.from_pretrained(
            MODEL_ID,
            device_map=self.device,
            dtype=dtype,
        )
        self.normalize_text = NORMALIZE_TEXT and _text_normalization_available()
        logger.info(
            "OmniVoice ready at %s Hz (text normalization %s).",
            self.model.sampling_rate,
            "on" if self.normalize_text else "off",
        )

    def generate(self, request: GenerateRequest) -> tuple[bytes, int, float | None, int]:
        return self.generate_batch([request])[0]

    def _generate_audio(self, requests: list[GenerateRequest], *, normalize: bool = True) -> list[np.ndarray]:
        if self.model is None:
            raise RuntimeError("OmniVoice model is not loaded")

        if len(requests) > 1 and any(request.seed is not None for request in requests):
            return [self._generate_audio([request], normalize=normalize)[0] for request in requests]
        prompts = [translate_generation_prompt(request.voice, request.text) for request in requests]
        use_normalizer = self.normalize_text and normalize
        texts = [prepare_for_normalization(prompt.text) if use_normalizer else prompt.text for prompt in prompts]
        with self._generate_lock:
            if requests[0].seed is not None:
                torch.manual_seed(requests[0].seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(requests[0].seed)
            clone_prompts = [self._voice_clone_prompt(request.voice_id) if request.voice_id else None for request in requests]
            if any(clone_prompts) and not all(clone_prompts):
                raise RuntimeError("OmniVoice cannot mix designed and undesigned voices in one native batch.")
            audio = self.model.generate(
                text=texts,
                language=[request.language for request in requests],
                instruct=[prompt.instruct for prompt in prompts],
                voice_clone_prompt=clone_prompts if all(clone_prompts) else None,
                speed=[prompt.speed for prompt in prompts],
                num_step=NUM_STEPS,
                class_temperature=0.0,
                postprocess_output=True,
                # Applies to the target text only; clone-prompt ref_text is untouched.
                normalize_text=use_normalizer,
            )

        # OmniVoice.generate returns list[np.ndarray]; its package is untyped.
        return cast(list[np.ndarray], audio)

    def _voice_clone_prompt(self, voice_id: str) -> object:
        if self.model is None:
            raise RuntimeError("OmniVoice model is not loaded")
        cached = self._voice_clone_prompts.get(voice_id)
        if cached is not None:
            return cached
        stored = self._voice_store.get(voice_id)
        prompt = self.model.create_voice_clone_prompt(
            ref_audio=str(self._voice_store.sample_path(voice_id)),
            ref_text=stored.ref_text,
        )
        self._voice_clone_prompts[voice_id] = prompt
        return prompt

    def design_voice(self, request: DesignVoiceRequest) -> StoredVoice:
        if self.model is None:
            raise RuntimeError("OmniVoice model is not loaded")
        with self._generate_lock:
            translated = translate_generation_prompt(request.voice, VOICE_DESIGN_TEXT)
            # The stored ref_text must match the enrollment sample word for word,
            # so the sample is spoken from the exact text that is saved with it.
            audio, _similarity, _attempts = self._generate_valid_audio(
                GenerateRequest(
                    text=VOICE_DESIGN_TEXT,
                    voice=request.voice,
                    language=request.language,
                ),
                1,
                normalize=False,
            )
            stored = self._voice_store.create(
                model=MODEL_ID,
                instruct=translated.instruct or "",
                ref_text=translated.text,
                audio=audio,
                sampling_rate=self.model.sampling_rate,
            )
            self._voice_clone_prompts[stored.id] = self.model.create_voice_clone_prompt(
                ref_audio=str(self._voice_store.sample_path(stored.id)),
                ref_text=stored.ref_text,
            )
            self._speaker_guard.calibrate(stored.id)
            return stored

    def _generate_probe(self, voice_id: str, text: str, seed: int) -> tuple[np.ndarray, int]:
        if self.model is None:
            raise RuntimeError("OmniVoice model is not loaded")
        request = GenerateRequest(
            text=text, voice=self._voice_store.get(voice_id).instruct or None, voice_id=voice_id, seed=seed
        )
        return self._generate_audio([request])[0], self.model.sampling_rate

    def _check_audio(self, request: GenerateRequest, audio: np.ndarray, sampling_rate: int) -> SpeakerCheck:
        validate_generated_audio(audio, sampling_rate)
        return self._speaker_guard.check(
            request.voice_id,
            audio,
            sampling_rate,
            drift_margin=request.drift_margin,
            cast_voice_ids=request.cast_voice_ids,
            min_similarity=request.min_voice_similarity,
        )

    def _generate_valid_audio(
        self,
        request: GenerateRequest,
        request_number: int,
        initial: np.ndarray | None = None,
        *,
        normalize: bool = True,
    ) -> tuple[np.ndarray, float | None, int]:
        if self.model is None:
            raise RuntimeError("OmniVoice model is not loaded")
        sampling_rate = self.model.sampling_rate

        def generate(attempt: int) -> tuple[np.ndarray, int]:
            attempt_request = request
            if request.seed is not None:
                attempt_request = request.model_copy(update={"seed": seed_for_attempt(request.seed, attempt)})
            return self._generate_audio([attempt_request], normalize=normalize)[0], sampling_rate

        text = request.text.replace("\n", " ")[:120]
        audio, _rate, check, attempts = generate_checked(
            generate,
            lambda candidate, rate: self._check_audio(request, candidate, rate),
            attempts=request.quality_attempts,
            label=f"request {request_number} ({text!r})",
            initial=None if initial is None else (initial, sampling_rate),
        )
        return audio, check.similarity, attempts

    def generate_batch(self, requests: list[GenerateRequest]) -> list[tuple[bytes, int, float | None, int]]:
        if self.model is None:
            raise RuntimeError("OmniVoice model is not loaded")

        has_voice_ids = [bool(request.voice_id) for request in requests]
        can_native_batch = all(has_voice_ids) or not any(has_voice_ids)
        if NATIVE_BATCHING and len(requests) > 1 and can_native_batch:
            # Each native output counts as the item's first attempt; rejected
            # items are retried individually with their next attempt seed.
            audios = self._generate_audio(requests)
            valid_audios = [
                self._generate_valid_audio(request, index, initial=audio)
                for index, (request, audio) in enumerate(zip(requests, audios, strict=True), start=1)
            ]
        else:
            valid_audios = [self._generate_valid_audio(request, index) for index, request in enumerate(requests, start=1)]

        return [
            (*_encode_audio(audio, self.model.sampling_rate), similarity, attempts)
            for audio, similarity, attempts in valid_audios
        ]


runtime = OmniVoiceRuntime()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Startup cannot serve requests until the model is ready. Loading on the
    # main thread also avoids a safetensors/Python 3.13 lock inversion seen
    # when model deserialization itself launches worker threads.
    runtime.load()
    yield


app = FastAPI(title="Story Manager OmniVoice Adapter", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ready" if runtime.model is not None else "loading",
        "model": MODEL_ID,
        "device": runtime.device,
        "num_steps": NUM_STEPS,
        "max_batch_size": MAX_BATCH_SIZE,
        "native_batching": NATIVE_BATCHING,
        "normalize_text": runtime.normalize_text,
        "quality_attempts": QUALITY_ATTEMPTS,
        "voice_store": str(VOICE_STORE_PATH),
    }


@app.post("/voices/design", response_model=DesignVoiceResponse)
async def design_voice(request: DesignVoiceRequest) -> DesignVoiceResponse:
    try:
        stored = await asyncio.to_thread(runtime.design_voice, request)
    except Exception as exc:
        logger.exception("OmniVoice voice design failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return DesignVoiceResponse(
        id=stored.id,
        voice=request.voice,
        sample_text=stored.ref_text,
        sample_url=f"/voices/{stored.id}/sample",
    )


@app.get("/voices/{voice_id}/sample")
async def voice_sample(voice_id: str) -> FileResponse:
    try:
        sample_path = runtime._voice_store.sample_path(voice_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(sample_path, media_type="audio/wav", filename=f"{voice_id}.wav")


@app.post("/generate")
async def generate(request: GenerateRequest) -> Response:
    try:
        audio, duration_ms, similarity, attempts = await asyncio.to_thread(runtime.generate, request)
    except Exception as exc:
        logger.exception("OmniVoice generation failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(
        audio,
        media_type="audio/mpeg",
        headers={
            "X-Audio-Duration-Ms": str(duration_ms),
            "X-OmniVoice-Device": runtime.device,
            "X-Generation-Attempts": str(attempts),
            **({"X-Voice-Similarity": f"{similarity:.6f}"} if similarity is not None else {}),
        },
    )


@app.post("/generate-batch", response_model=BatchGenerateResponse)
async def generate_batch(request: BatchGenerateRequest) -> BatchGenerateResponse:
    try:
        generated = await asyncio.to_thread(runtime.generate_batch, request.requests)
    except Exception as exc:
        logger.exception("OmniVoice batch generation failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return BatchGenerateResponse(
        items=[
            BatchGenerateItem(
                audio_base64=base64.b64encode(audio).decode("ascii"),
                duration_ms=duration_ms,
                voice_similarity=similarity,
                attempts=attempts,
            )
            for audio, duration_ms, similarity, attempts in generated
        ]
    )
