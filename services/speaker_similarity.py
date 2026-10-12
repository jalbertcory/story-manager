"""Lazy speaker verification shared by local TTS adapters.

The default verifier is WeSpeaker's VoxCeleb ResNet34-LM exported to ONNX. On the
voice-consistency benchmark it separates "same designed voice, new sentence" from
"different designed voice, same gender" far better than the WavLM x-vector it
replaced (same-gender d' 2.5 -> 5.7, EER 3.9% -> 0.4%) while running ~4x faster
on CPU. Set ``SPEAKER_VERIFIER_MODEL=microsoft/wavlm-base-plus-sv`` to fall back
to the transformers x-vector model.

Scores from different models live on different scales, so every threshold that
compares raw cosine similarities comes from :data:`CALIBRATIONS` for the active
model instead of being hard-coded by callers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
import wave

import numpy as np

from services.tts_consistency import candidate_has_enough_speech

if TYPE_CHECKING:
    import onnxruntime
    from transformers import FeatureExtractionMixin, PreTrainedModel

WESPEAKER_RESNET34 = "Wespeaker/wespeaker-voxceleb-resnet34-LM"
WAVLM_XVECTOR = "microsoft/wavlm-base-plus-sv"
# Hub weights are pinned: a changed upstream file would silently move every
# similarity score and invalidate the calibration profiles stored per voice.
PINNED_REVISIONS = {
    WESPEAKER_RESNET34: "f0c48c298fd835726c27956a5d617bad7115627e",
    WAVLM_XVECTOR: "feb593a6c23c1cc3d9510425c29b0a14d2b07b1e",
}
MODEL_ID = os.getenv("SPEAKER_VERIFIER_MODEL", WESPEAKER_RESNET34)
REVISION = os.getenv("SPEAKER_VERIFIER_REVISION") or PINNED_REVISIONS.get(MODEL_ID)
DEVICE = os.getenv("SPEAKER_VERIFIER_DEVICE", "cpu")
SAMPLING_RATE = 16_000


@dataclass(frozen=True)
class VerifierCalibration:
    """Model-specific score scales used by drift and roster checks."""

    family: str
    # Designed voices whose sample scores above this against an existing cast
    # voice are treated as duplicates. For WeSpeaker, distinct benchmark voices
    # scored 0.14-0.42 sample-to-sample; the one pair at 0.52 produced takes
    # scoring up to 0.65 against each other, inside the bottom 1% of genuine
    # takes (0.58).
    roster_max_similarity: float
    # Lower bound on the per-voice spread used to turn the drift margin (in
    # standard deviations) into a similarity floor, so a voice whose probes
    # happened to agree closely is not rejected for ordinary variation.
    drift_std_floor: float


CALIBRATIONS = {
    "wespeaker": VerifierCalibration(family="wespeaker", roster_max_similarity=0.45, drift_std_floor=0.05),
    "xvector": VerifierCalibration(family="xvector", roster_max_similarity=0.9, drift_std_floor=0.012),
}


def model_family(model_id: str) -> str:
    """Return the embedder family that loads ``model_id``."""
    lowered = model_id.lower()
    if lowered.endswith(".onnx") or lowered.startswith("wespeaker/"):
        return "wespeaker"
    return "xvector"


def calibration_for(model_id: str = MODEL_ID) -> VerifierCalibration:
    return CALIBRATIONS[model_family(model_id)]


class _Embedder(Protocol):
    def __call__(self, audio: np.ndarray) -> np.ndarray: ...


def _resample(audio: np.ndarray, source_rate: int) -> np.ndarray:
    """Band-limited resampling to 16 kHz without an audio-library dependency."""
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if source_rate == SAMPLING_RATE:
        return samples
    if source_rate <= 0:
        raise ValueError("source sampling rate must be positive")
    target_length = max(1, round(samples.size * SAMPLING_RATE / source_rate))
    spectrum = np.fft.rfft(samples.astype(np.float64))
    bins = target_length // 2 + 1
    if bins <= spectrum.size:
        spectrum = spectrum[:bins]
    else:
        spectrum = np.pad(spectrum, (0, bins - spectrum.size))
    resampled = np.fft.irfft(spectrum, n=target_length) * (target_length / samples.size)
    return resampled.astype(np.float32)


def _hz_to_mel(frequency: np.ndarray | float) -> np.ndarray:
    return np.asarray(1127.0 * np.log(1.0 + np.asarray(frequency) / 700.0))


@lru_cache(maxsize=4)
def _mel_banks(num_bins: int, fft_size: int, sampling_rate: int) -> np.ndarray:
    low, high = _hz_to_mel(20.0), _hz_to_mel(sampling_rate / 2)
    delta = (high - low) / (num_bins + 1)
    left = low + delta * np.arange(num_bins)[:, None]
    center, right = left + delta, left + 2 * delta
    mel = _hz_to_mel(sampling_rate / fft_size * np.arange(fft_size // 2))[None, :]
    banks = np.maximum(0.0, np.minimum((mel - left) / (center - left), (right - mel) / (right - center)))
    return np.pad(banks, ((0, 0), (0, 1)))


def kaldi_fbank(audio: np.ndarray, num_bins: int = 80) -> np.ndarray:
    """Mean-normalized log-mel features matching WeSpeaker's Kaldi front end.

    Equivalent to ``torchaudio.compliance.kaldi.fbank`` with a 25 ms Hamming
    window, 10 ms shift, no dither and 16-bit sample scaling, followed by
    utterance-level mean normalization.
    """
    frame, shift, fft_size = 400, 160, 512
    wav = np.asarray(audio, dtype=np.float64).reshape(-1) * 32768.0
    if wav.size < frame:
        raise ValueError("audio is too short for speaker features")
    count = 1 + (wav.size - frame) // shift
    frames = wav[np.arange(frame)[None, :] + shift * np.arange(count)[:, None]]
    frames = frames - frames.mean(axis=1, keepdims=True)
    frames = frames - 0.97 * np.concatenate([frames[:, :1], frames[:, :-1]], axis=1)
    power = np.abs(np.fft.rfft(frames * np.hamming(frame), n=fft_size)) ** 2
    feats = np.log(np.maximum(power @ _mel_banks(num_bins, fft_size, SAMPLING_RATE).T, np.finfo(np.float32).eps))
    return np.asarray(feats - feats.mean(axis=0), dtype=np.float32)


def _wespeaker_onnx_path(model_id: str, revision: str | None) -> str:
    if model_id.lower().endswith(".onnx"):
        return model_id
    from huggingface_hub import hf_hub_download

    repo_name = model_id.split("/", 1)[1]
    filename = repo_name.removeprefix("wespeaker-").replace("-", "_") + ".onnx"
    return str(hf_hub_download(model_id, filename, revision=revision))


class _WeSpeakerEmbedder:
    def __init__(self, model_id: str, revision: str | None, device: str) -> None:
        import onnxruntime as ort

        providers = ["CPUExecutionProvider"]
        if device.startswith("cuda") and "CUDAExecutionProvider" in ort.get_available_providers():
            providers.insert(0, "CUDAExecutionProvider")
        self._session: onnxruntime.InferenceSession = ort.InferenceSession(
            _wespeaker_onnx_path(model_id, revision), providers=providers
        )
        self._input = self._session.get_inputs()[0].name

    def __call__(self, audio: np.ndarray) -> np.ndarray:
        outputs = self._session.run(None, {self._input: kaldi_fbank(audio)[None]})
        return np.asarray(outputs[0], dtype=np.float32).reshape(-1)


class _XVectorEmbedder:
    def __init__(self, model_id: str, revision: str | None, device: str) -> None:
        from transformers import AutoFeatureExtractor, AutoModelForAudioXVector

        self._device = device
        self._extractor: FeatureExtractionMixin = AutoFeatureExtractor.from_pretrained(model_id, revision=revision)
        self._model: PreTrainedModel = AutoModelForAudioXVector.from_pretrained(model_id, revision=revision).to(device).eval()

    def __call__(self, audio: np.ndarray) -> np.ndarray:
        import torch

        inputs = self._extractor(audio, sampling_rate=SAMPLING_RATE, return_tensors="pt", padding=True)
        inputs = {name: value.to(self._device) for name, value in inputs.items()}
        with torch.inference_mode():
            embedding = self._model(**inputs).embeddings[0]
        return np.asarray(embedding.float().cpu().numpy(), dtype=np.float32).reshape(-1)


def _build_embedder(model_id: str, revision: str | None, device: str) -> _Embedder:
    if model_family(model_id) == "wespeaker":
        return _WeSpeakerEmbedder(model_id, revision, device)
    return _XVectorEmbedder(model_id, revision, device)


def _default_revision(model_id: str) -> str | None:
    return REVISION if model_id == MODEL_ID else PINNED_REVISIONS.get(model_id)


class SpeakerVerifier:
    """Compare generated speech with stored character enrollment samples."""

    def __init__(
        self,
        model_id: str = MODEL_ID,
        device: str = DEVICE,
        embedder: _Embedder | None = None,
        revision: str | None = None,
    ) -> None:
        self.model_id = model_id
        self.revision = revision if revision is not None else _default_revision(model_id)
        self.calibration = calibration_for(model_id)
        self._device = device
        self._embedder = embedder
        self._reference_embeddings: dict[str, np.ndarray] = {}

    @property
    def profile_key(self) -> str:
        """Identify the exact weights, so calibrations never mix score scales."""
        return f"{self.model_id}@{self.revision}" if self.revision else self.model_id

    def embedding(self, audio: np.ndarray, sampling_rate: int) -> np.ndarray:
        if self._embedder is None:
            self._embedder = _build_embedder(self.model_id, self.revision, self._device)
        vector = np.asarray(self._embedder(_resample(audio, sampling_rate)), dtype=np.float64).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            raise RuntimeError("Speaker verification produced an empty embedding.")
        return vector / norm

    def reference_embedding(self, reference_key: str, reference_path: Path) -> np.ndarray:
        reference = self._reference_embeddings.get(reference_key)
        if reference is None:
            reference_audio, reference_rate = _read_pcm_wav(reference_path)
            reference = self.embedding(reference_audio, reference_rate)
            self._reference_embeddings[reference_key] = reference
        return reference

    def similarities(
        self,
        references: Mapping[str, Path],
        candidate: np.ndarray,
        sampling_rate: int,
    ) -> dict[str, float] | None:
        """Score one utterance against several references, embedding it once.

        Returns ``None`` when the utterance is too short to score reliably.
        """
        if not candidate_has_enough_speech(np.asarray(candidate).size, sampling_rate):
            return None
        if not references:
            return {}
        candidate_embedding = self.embedding(candidate, sampling_rate)
        return {
            key: float(np.dot(self.reference_embedding(key, path), candidate_embedding)) for key, path in references.items()
        }

    def similarity(
        self,
        reference_key: str,
        reference_path: Path,
        candidate: np.ndarray,
        sampling_rate: int,
    ) -> float | None:
        scores = self.similarities({reference_key: reference_path}, candidate, sampling_rate)
        return None if scores is None else scores[reference_key]

    def forget(self, reference_key: str) -> None:
        self._reference_embeddings.pop(reference_key, None)


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
