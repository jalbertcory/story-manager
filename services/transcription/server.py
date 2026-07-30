"""FastAPI service exposing WhisperX transcription with aligned word timestamps."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import tempfile
import threading

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MODEL_ID = os.getenv("WHISPER_MODEL", "large-v3")
DEFAULT_LANGUAGE = (os.getenv("WHISPER_LANGUAGE") or "").strip() or None
DEVICE_SETTING = os.getenv("WHISPER_DEVICE", "auto")
COMPUTE_TYPE_SETTING = os.getenv("WHISPER_COMPUTE_TYPE", "auto")
BATCH_SIZE = max(1, int(os.getenv("WHISPER_BATCH_SIZE", "4")))
MODEL_CACHE = os.getenv("WHISPER_MODEL_CACHE", "/models")
API_KEY = os.getenv("TRANSCRIPTION_API_KEY")
MAX_UPLOAD_BYTES = int(os.getenv("TRANSCRIPTION_MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))
UPLOAD_CHUNK_BYTES = 1024 * 1024


class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float
    score: float = 1.0


class TranscriptionResponse(BaseModel):
    language: str | None
    duration: float
    words: list[WordTimestamp]


def authorize(authorization: str | None = Header(default=None)) -> None:
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Invalid transcription service API key.")


class WhisperXRuntime:
    def __init__(self) -> None:
        self.model = None
        self.device = "unloaded"
        self.compute_type = "unloaded"
        self._align_models = {}
        self._lock = threading.Lock()

    def load(self) -> None:
        import torch
        import whisperx

        self.device = ("cuda" if torch.cuda.is_available() else "cpu") if DEVICE_SETTING == "auto" else DEVICE_SETTING
        self.compute_type = (
            ("float16" if self.device == "cuda" else "int8") if COMPUTE_TYPE_SETTING == "auto" else COMPUTE_TYPE_SETTING
        )
        logger.info(
            "Loading WhisperX model %s on %s (%s).",
            MODEL_ID,
            self.device,
            self.compute_type,
        )
        self.model = whisperx.load_model(
            MODEL_ID,
            self.device,
            compute_type=self.compute_type,
            download_root=MODEL_CACHE,
            language=DEFAULT_LANGUAGE,
        )
        if DEFAULT_LANGUAGE:
            logger.info("Preloading WhisperX alignment model for %s.", DEFAULT_LANGUAGE)
            self._align_models[DEFAULT_LANGUAGE] = whisperx.load_align_model(
                language_code=DEFAULT_LANGUAGE,
                device=self.device,
                model_dir=MODEL_CACHE,
            )
        logger.info("WhisperX transcription model is ready.")

    def transcribe(self, audio_path: Path, language: str | None) -> TranscriptionResponse:
        import whisperx

        if self.model is None:
            raise RuntimeError("WhisperX model is not loaded.")
        with self._lock:
            audio = whisperx.load_audio(str(audio_path))
            requested_language = language or DEFAULT_LANGUAGE
            result = self.model.transcribe(
                audio,
                batch_size=BATCH_SIZE,
                language=requested_language,
            )
            detected_language = result.get("language") or requested_language
            if not detected_language:
                raise RuntimeError("WhisperX could not determine the audio language.")
            if detected_language not in self._align_models:
                self._align_models[detected_language] = whisperx.load_align_model(
                    language_code=detected_language,
                    device=self.device,
                    model_dir=MODEL_CACHE,
                )
            align_model, metadata = self._align_models[detected_language]
            aligned = whisperx.align(
                result["segments"],
                align_model,
                metadata,
                audio,
                self.device,
                return_char_alignments=False,
            )

        words = []
        for segment in aligned.get("segments") or []:
            for raw_word in segment.get("words") or []:
                if raw_word.get("start") is None or raw_word.get("end") is None:
                    continue
                text = str(raw_word.get("word") or "").strip()
                if text and float(raw_word["end"]) > float(raw_word["start"]):
                    words.append(
                        WordTimestamp(
                            word=text,
                            start=float(raw_word["start"]),
                            end=float(raw_word["end"]),
                            score=max(0.0, min(1.0, float(raw_word.get("score", 1.0)))),
                        )
                    )
        if not words:
            raise RuntimeError("WhisperX produced no aligned word timestamps.")
        duration = len(audio) / 16000
        return TranscriptionResponse(
            language=detected_language,
            duration=duration,
            words=words,
        )


runtime = WhisperXRuntime()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(runtime.load)
    yield


app = FastAPI(title="Story Manager WhisperX Transcription", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ready" if runtime.model is not None else "loading",
        "model": MODEL_ID,
        "device": runtime.device,
        "compute_type": runtime.compute_type,
        "batch_size": BATCH_SIZE,
        "default_language": DEFAULT_LANGUAGE,
    }


@app.post(
    "/transcribe",
    response_model=TranscriptionResponse,
    dependencies=[Depends(authorize)],
)
async def transcribe(
    file: UploadFile = File(...),
    model: str | None = Form(default=None),
    language: str | None = Form(default=None),
) -> TranscriptionResponse:
    if model and model != MODEL_ID:
        raise HTTPException(
            status_code=409,
            detail=f"Service has {MODEL_ID!r} loaded, not requested model {model!r}.",
        )
    suffix = Path(file.filename or "chapter.flac").suffix or ".flac"
    temp_path = None
    written = 0
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            temp_path = Path(handle.name)
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Audio clip exceeds service upload limit.")
                handle.write(chunk)
        return await asyncio.to_thread(runtime.transcribe, temp_path, language)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("WhisperX transcription failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
