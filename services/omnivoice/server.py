"""FastAPI adapter exposing official OmniVoice through Story Manager's API."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from io import BytesIO
import logging
import os
from pathlib import Path
import threading

# Let unsupported MPS operations fall back to CPU rather than terminating a
# long audiobook run. This must be set before importing torch.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import numpy as np  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from omnivoice import OmniVoice  # noqa: E402
from omnivoice.utils.common import get_best_device  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from pydub import AudioSegment  # noqa: E402
import torch  # noqa: E402

from .audio_quality import AudioQualityError, validate_generated_audio  # noqa: E402
from .prompt import translate_generation_prompt  # noqa: E402
from .voice_store import StoredVoice, VoiceStore  # noqa: E402
from services.speaker_similarity import get_speaker_verifier  # noqa: E402
from services.tts_consistency import seed_for_attempt  # noqa: E402

logger = logging.getLogger(__name__)

MODEL_ID = os.getenv("OMNIVOICE_MODEL", "k2-fsa/OmniVoice")
DEVICE = os.getenv("OMNIVOICE_DEVICE", "auto")
NUM_STEPS = int(os.getenv("OMNIVOICE_NUM_STEPS", "16"))
MP3_BITRATE = os.getenv("OMNIVOICE_MP3_BITRATE", "96k")
MAX_BATCH_SIZE = max(1, int(os.getenv("OMNIVOICE_MAX_BATCH_SIZE", "8")))
NATIVE_BATCHING = os.getenv("OMNIVOICE_NATIVE_BATCHING", "false").lower() in {"1", "true", "yes"}
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
    min_voice_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)
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


class OmniVoiceRuntime:
    def __init__(self) -> None:
        self.model: OmniVoice | None = None
        self.device = "unloaded"
        self._generate_lock = threading.RLock()
        self._voice_store = VoiceStore(VOICE_STORE_PATH)
        self._voice_clone_prompts: dict[str, object] = {}

    def load(self) -> None:
        self.device = get_best_device() if DEVICE == "auto" else DEVICE
        dtype = torch.float32 if self.device == "cpu" else torch.float16
        logger.info("Loading %s on %s (%s).", MODEL_ID, self.device, dtype)
        self.model = OmniVoice.from_pretrained(
            MODEL_ID,
            device_map=self.device,
            dtype=dtype,
        )
        logger.info("OmniVoice ready at %s Hz.", self.model.sampling_rate)

    def generate(self, request: GenerateRequest) -> tuple[bytes, int, float | None, int]:
        return self.generate_batch([request])[0]

    def _generate_audio(self, requests: list[GenerateRequest]) -> list[np.ndarray]:
        if self.model is None:
            raise RuntimeError("OmniVoice model is not loaded")

        if len(requests) > 1 and any(request.seed is not None for request in requests):
            return [self._generate_audio([request])[0] for request in requests]
        prompts = [translate_generation_prompt(request.voice, request.text) for request in requests]
        with self._generate_lock:
            if requests[0].seed is not None:
                torch.manual_seed(requests[0].seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(requests[0].seed)
            clone_prompts = [self._voice_clone_prompt(request.voice_id) if request.voice_id else None for request in requests]
            if any(clone_prompts) and not all(clone_prompts):
                raise RuntimeError("OmniVoice cannot mix designed and undesigned voices in one native batch.")
            return self.model.generate(
                text=[prompt.text for prompt in prompts],
                language=[request.language for request in requests],
                instruct=[prompt.instruct for prompt in prompts],
                voice_clone_prompt=clone_prompts if all(clone_prompts) else None,
                speed=[prompt.speed for prompt in prompts],
                num_step=NUM_STEPS,
                class_temperature=0.0,
                postprocess_output=True,
            )

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
            audio, _similarity, _attempts = self._generate_valid_audio(
                GenerateRequest(
                    text=VOICE_DESIGN_TEXT,
                    voice=request.voice,
                    language=request.language,
                ),
                1,
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
            return stored

    def _generate_valid_audio(self, request: GenerateRequest, request_number: int) -> tuple[np.ndarray, float | None, int]:
        if self.model is None:
            raise RuntimeError("OmniVoice model is not loaded")

        last_error = None
        for attempt in range(1, request.quality_attempts + 1):
            attempt_request = request
            if request.seed is not None:
                attempt_request = request.model_copy(update={"seed": seed_for_attempt(request.seed, attempt)})
            audio = self._generate_audio([attempt_request])[0]
            try:
                validate_generated_audio(audio, self.model.sampling_rate)
                similarity = self._voice_similarity(request, audio)
                if (
                    request.min_voice_similarity is not None
                    and similarity is not None
                    and similarity < request.min_voice_similarity
                ):
                    raise AudioQualityError(f"speaker similarity {similarity:.3f} is below {request.min_voice_similarity:.3f}")
                return audio, similarity, attempt
            except AudioQualityError as exc:
                last_error = exc
                logger.warning(
                    "Rejected generated audio for request %d on quality attempt %d/%d: %s",
                    request_number,
                    attempt,
                    request.quality_attempts,
                    exc,
                )

        text = request.text.replace("\n", " ")[:120]
        raise AudioQualityError(
            f"request {request_number} ({text!r}) failed quality validation after "
            f"{request.quality_attempts} attempts: {last_error}"
        ) from last_error

    def _voice_similarity(self, request: GenerateRequest, audio: np.ndarray) -> float | None:
        if not request.voice_id:
            return None
        sample_path = self._voice_store.sample_path(request.voice_id)
        return get_speaker_verifier().similarity(
            request.voice_id,
            sample_path,
            audio,
            self.model.sampling_rate,
        )

    def generate_batch(self, requests: list[GenerateRequest]) -> list[tuple[bytes, int, float | None, int]]:
        if self.model is None:
            raise RuntimeError("OmniVoice model is not loaded")

        has_voice_ids = [bool(request.voice_id) for request in requests]
        can_native_batch = all(has_voice_ids) or not any(has_voice_ids)
        if NATIVE_BATCHING and len(requests) > 1 and can_native_batch:
            audios = self._generate_audio(requests)
            valid_audios: list[tuple[np.ndarray, float | None, int]] = []
            for index, (request, audio) in enumerate(zip(requests, audios, strict=True), start=1):
                try:
                    validate_generated_audio(audio, self.model.sampling_rate)
                    similarity = self._voice_similarity(request, audio)
                    if (
                        request.min_voice_similarity is not None
                        and similarity is not None
                        and similarity < request.min_voice_similarity
                    ):
                        raise AudioQualityError(
                            f"speaker similarity {similarity:.3f} is below {request.min_voice_similarity:.3f}"
                        )
                    valid_audios.append((audio, similarity, 1))
                except AudioQualityError as exc:
                    logger.warning(
                        "Rejected native batch output for request %d; regenerating individually: %s",
                        index,
                        exc,
                    )
                    valid_audios.append(self._generate_valid_audio(request, index))
        else:
            valid_audios = [self._generate_valid_audio(request, index) for index, request in enumerate(requests, start=1)]

        return [
            (*_encode_audio(audio, self.model.sampling_rate), similarity, attempts)
            for audio, similarity, attempts in valid_audios
        ]


runtime = OmniVoiceRuntime()


@asynccontextmanager
async def lifespan(_app: FastAPI):
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
