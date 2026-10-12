from pathlib import Path
import wave

import numpy as np
import pytest

from services.speaker_similarity import (
    WAVLM_XVECTOR,
    WESPEAKER_RESNET34,
    SpeakerVerifier,
    _resample,
    calibration_for,
    kaldi_fbank,
    model_family,
)


def _tone(frequency: float, seconds: float = 1.5, rate: int = 16_000) -> np.ndarray:
    time = np.arange(round(seconds * rate)) / rate
    return (0.2 * np.sin(2 * np.pi * frequency * time)).astype(np.float32)


def _write_wav(path: Path, audio: np.ndarray, rate: int = 16_000) -> Path:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(np.clip(audio * 32767, -32768, 32767).astype("<i2").tobytes())
    return path


def _dominant_frequency_embedder(audio: np.ndarray) -> np.ndarray:
    """Embed a clip as a one-hot of its dominant 100 Hz band."""
    spectrum = np.abs(np.fft.rfft(audio))
    vector = np.zeros(40)
    vector[min(39, int(np.argmax(spectrum) * 16_000 / audio.size // 100))] = 1.0
    return vector + 0.01


def test_model_family_and_calibration_select_the_matching_score_scale():
    assert model_family(WESPEAKER_RESNET34) == "wespeaker"
    assert model_family("/models/custom.onnx") == "wespeaker"
    assert model_family(WAVLM_XVECTOR) == "xvector"
    assert calibration_for(WESPEAKER_RESNET34).roster_max_similarity < calibration_for(WAVLM_XVECTOR).roster_max_similarity
    assert calibration_for(WESPEAKER_RESNET34).drift_std_floor > calibration_for(WAVLM_XVECTOR).drift_std_floor


def test_kaldi_fbank_uses_25ms_frames_with_10ms_shift_and_mean_normalization():
    features = kaldi_fbank(_tone(220, seconds=1.0))

    assert features.shape == (1 + (16_000 - 400) // 160, 80)
    assert features.dtype == np.float32
    np.testing.assert_allclose(features.mean(axis=0), 0.0, atol=1e-3)


def test_kaldi_fbank_rejects_clips_shorter_than_one_frame():
    with pytest.raises(ValueError, match="too short"):
        kaldi_fbank(np.zeros(399, dtype=np.float32))


def test_resample_preserves_duration_and_pitch():
    resampled = _resample(_tone(440, seconds=1.0, rate=24_000), 24_000)

    assert resampled.size == 16_000
    assert np.argmax(np.abs(np.fft.rfft(resampled))) == 440


def test_similarities_embed_the_candidate_once_against_every_reference(tmp_path):
    calls = []

    def embedder(audio: np.ndarray) -> np.ndarray:
        calls.append(audio.size)
        return _dominant_frequency_embedder(audio)

    verifier = SpeakerVerifier(model_id=WESPEAKER_RESNET34, embedder=embedder)
    references = {
        "low": _write_wav(tmp_path / "low.wav", _tone(150)),
        "high": _write_wav(tmp_path / "high.wav", _tone(1150)),
    }

    scores = verifier.similarities(references, _tone(150, rate=24_000), 24_000)

    assert scores is not None
    assert scores["low"] > 0.99
    assert scores["high"] < 0.1
    assert len(calls) == 3
    verifier.similarities(references, _tone(1150), 16_000)
    assert len(calls) == 4, "reference embeddings are cached"


def test_similarities_skip_clips_too_short_to_verify(tmp_path):
    verifier = SpeakerVerifier(model_id=WESPEAKER_RESNET34, embedder=_dominant_frequency_embedder)

    assert verifier.similarities({"a": tmp_path / "missing.wav"}, _tone(150, seconds=0.5), 16_000) is None
    assert verifier.similarities({}, _tone(150), 16_000) == {}
