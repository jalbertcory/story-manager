"""FastAPI adapter exposing official OmniVoice through Story Manager's API."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
import logging
import os
import threading

# Let unsupported MPS operations fall back to CPU rather than terminating a
# long audiobook run. This must be set before importing torch.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from omnivoice import OmniVoice
from omnivoice.utils.common import get_best_device
from pydantic import BaseModel, Field
from pydub import AudioSegment
import torch

from .prompt import translate_generation_prompt

logger = logging.getLogger(__name__)

MODEL_ID = os.getenv("OMNIVOICE_MODEL", "k2-fsa/OmniVoice")
DEVICE = os.getenv("OMNIVOICE_DEVICE", "auto")
NUM_STEPS = int(os.getenv("OMNIVOICE_NUM_STEPS", "16"))
MP3_BITRATE = os.getenv("OMNIVOICE_MP3_BITRATE", "96k")


class GenerateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str | None = None
    language: str | None = None


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
        if self.model is None:
            raise RuntimeError("OmniVoice model is not loaded")

        prompt = translate_generation_prompt(request.voice, request.text)
        with self._generate_lock:
            audio = self.model.generate(
                text=prompt.text,
                language=request.language,
                instruct=prompt.instruct,
                speed=prompt.speed,
                num_step=NUM_STEPS,
                class_temperature=0.0,
                postprocess_output=True,
            )[0]

        pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        segment = AudioSegment(
            pcm.tobytes(),
            frame_rate=self.model.sampling_rate,
            sample_width=2,
            channels=1,
        )
        output = BytesIO()
        segment.export(output, format="mp3", bitrate=MP3_BITRATE)
        return output.getvalue(), len(segment)


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
