"""Lazy WavLM speaker verification shared by local TTS adapters."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import TYPE_CHECKING
import wave

import numpy as np
import torch
import torch.nn.functional as F

from services.tts_consistency import candidate_has_enough_speech

if TYPE_CHECKING:
    from transformers import Wav2Vec2FeatureExtractor, WavLMForXVector

MODEL_ID = os.getenv("SPEAKER_VERIFIER_MODEL", "microsoft/wavlm-base-plus-sv")
DEVICE = os.getenv("SPEAKER_VERIFIER_DEVICE", "cpu")
SAMPLING_RATE = 16_000


def _resample(audio: np.ndarray, source_rate: int) -> np.ndarray:
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if source_rate == SAMPLING_RATE:
        return samples
    if source_rate <= 0:
        raise ValueError("source sampling rate must be positive")
    target_length = max(1, round(samples.size * SAMPLING_RATE / source_rate))
    tensor = torch.from_numpy(samples).view(1, 1, -1)
    return np.asarray(F.interpolate(tensor, size=target_length, mode="linear", align_corners=False).view(-1).numpy())


class SpeakerVerifier:
    """Compare generated speech with a character enrollment sample."""

    def __init__(self) -> None:
        self._extractor: Wav2Vec2FeatureExtractor | None = None
        self._model: WavLMForXVector | None = None
        self._reference_embeddings: dict[str, torch.Tensor] = {}

    def _load(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoFeatureExtractor, WavLMForXVector

        self._extractor = AutoFeatureExtractor.from_pretrained(MODEL_ID)
        self._model = WavLMForXVector.from_pretrained(MODEL_ID).to(DEVICE).eval()

    def embedding(self, audio: np.ndarray, sampling_rate: int) -> torch.Tensor:
        self._load()
        if self._extractor is None or self._model is None:
            raise RuntimeError("Speaker verification model is not loaded.")
        samples = _resample(audio, sampling_rate)
        inputs = self._extractor(
            samples,
            sampling_rate=SAMPLING_RATE,
            return_tensors="pt",
            padding=True,
        )
        inputs = {name: value.to(DEVICE) for name, value in inputs.items()}
        with torch.inference_mode():
            embedding = self._model(**inputs).embeddings[0]
        return F.normalize(embedding.float().cpu(), dim=0)

    def similarity(
        self,
        reference_key: str,
        reference_path: Path,
        candidate: np.ndarray,
        sampling_rate: int,
    ) -> float | None:
        if not candidate_has_enough_speech(np.asarray(candidate).size, sampling_rate):
            return None
        reference = self._reference_embeddings.get(reference_key)
        if reference is None:
            reference_audio, reference_rate = _read_pcm_wav(reference_path)
            reference = self.embedding(reference_audio, reference_rate)
            self._reference_embeddings[reference_key] = reference
        candidate_embedding = self.embedding(candidate, sampling_rate)
        return float(F.cosine_similarity(reference, candidate_embedding, dim=0))


@lru_cache(maxsize=1)
def get_speaker_verifier() -> SpeakerVerifier:
    return SpeakerVerifier()


def _read_pcm_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        sampling_rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    if width != 2:
        raise ValueError(f"Speaker reference {path} must contain 16-bit PCM audio.")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, sampling_rate
