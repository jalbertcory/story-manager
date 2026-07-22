"""FastAPI adapter exposing official OmniVoice through Story Manager's API."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from io import BytesIO
import logging
import os
import threading

# Let unsupported MPS operations fall back to CPU rather than terminating a
# long audiobook run. This must be set before importing torch.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import numpy as np  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from omnivoice import OmniVoice  # noqa: E402
from omnivoice.utils.common import get_best_device  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from pydub import AudioSegment  # noqa: E402
import torch  # noqa: E402

from .prompt import translate_generation_prompt  # noqa: E402

logger = logging.getLogger(__name__)

MODEL_ID = os.getenv("OMNIVOICE_MODEL", "k2-fsa/OmniVoice")
DEVICE = os.getenv("OMNIVOICE_DEVICE", "auto")
NUM_STEPS = int(os.getenv("OMNIVOICE_NUM_STEPS", "16"))
MP3_BITRATE = os.getenv("OMNIVOICE_MP3_BITRATE", "96k")
MAX_BATCH_SIZE = max(1, int(os.getenv("OMNIVOICE_MAX_BATCH_SIZE", "8")))


class GenerateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str | None = None
    language: str | None = None


class BatchGenerateRequest(BaseModel):
    requests: list[GenerateRequest] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class BatchGenerateItem(BaseModel):
    audio_base64: str
    duration_ms: int


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
        self._generate_lock = threading.Lock()

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

    def generate(self, request: GenerateRequest) -> tuple[bytes, int]:
        return self.generate_batch([request])[0]

    def generate_batch(self, requests: list[GenerateRequest]) -> list[tuple[bytes, int]]:
        if self.model is None:
            raise RuntimeError("OmniVoice model is not loaded")

        prompts = [translate_generation_prompt(request.voice, request.text) for request in requests]
        with self._generate_lock:
            audios = self.model.generate(
                text=[prompt.text for prompt in prompts],
                language=[request.language for request in requests],
                instruct=[prompt.instruct for prompt in prompts],
                speed=[prompt.speed for prompt in prompts],
                num_step=NUM_STEPS,
                class_temperature=0.0,
                postprocess_output=True,
            )

        return [_encode_audio(audio, self.model.sampling_rate) for audio in audios]


runtime = OmniVoiceRuntime()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(runtime.load)
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
    }


@app.post("/generate")
async def generate(request: GenerateRequest) -> Response:
    try:
        audio, duration_ms = await asyncio.to_thread(runtime.generate, request)
    except Exception as exc:
        logger.exception("OmniVoice generation failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(
        audio,
        media_type="audio/mpeg",
        headers={
            "X-Audio-Duration-Ms": str(duration_ms),
            "X-OmniVoice-Device": runtime.device,
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
            )
            for audio, duration_ms in generated
        ]
    )
