"""Signal-level quality checks for generated OmniVoice audio."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class AudioQualityError(RuntimeError):
    """Raised when generated audio is unsafe to publish."""


@dataclass(frozen=True)
class AudioQualityReport:
    duration_seconds: float
    active_ratio: float
    rms_variation: float
    spectral_flatness: float
    zero_crossing_rate: float

    @property
    def has_stationary_mechanical_noise(self) -> bool:
        return (
            self.active_ratio > 0.80
            and self.rms_variation < 0.35
            and self.spectral_flatness > 0.065
            and self.zero_crossing_rate > 0.16
        )


def inspect_audio_quality(audio: np.ndarray, sampling_rate: int) -> AudioQualityReport:
    """Measure traits that distinguish speech from stationary mechanical noise."""
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not samples.size:
        raise AudioQualityError("generated audio is empty")
    if not np.isfinite(samples).all():
        raise AudioQualityError("generated audio contains non-finite samples")
    if sampling_rate <= 0:
        raise ValueError("sampling_rate must be positive")

    frame_size = min(1024, samples.size)
    if frame_size < 64:
        raise AudioQualityError("generated audio is too short to validate")
    hop_size = max(1, frame_size // 4)
    if samples.size == frame_size:
        frames = samples[np.newaxis, :]
    else:
        frames = np.lib.stride_tricks.sliding_window_view(samples, frame_size)[::hop_size]

    windowed = frames * np.hanning(frame_size)
    rms = np.sqrt(np.mean(windowed**2, axis=1) + 1e-12)
    active_threshold = max(float(rms.max()) * 0.03, 1e-4)
    active = rms > active_threshold
    active_rms = rms[active]
    active_frames = windowed[active]
    if not active_frames.size:
        raise AudioQualityError("generated audio is silent")

    magnitudes = np.abs(np.fft.rfft(active_frames, axis=1)) + 1e-12
    flatness = np.exp(np.mean(np.log(magnitudes), axis=1)) / np.mean(magnitudes, axis=1)
    zero_crossings = np.mean(samples[1:] * samples[:-1] < 0) if samples.size > 1 else 0.0

    return AudioQualityReport(
        duration_seconds=samples.size / sampling_rate,
        active_ratio=float(np.mean(active)),
        rms_variation=float(np.std(active_rms) / np.mean(active_rms)),
        spectral_flatness=float(np.median(flatness)),
        zero_crossing_rate=float(zero_crossings),
    )


def validate_generated_audio(audio: np.ndarray, sampling_rate: int) -> AudioQualityReport:
    """Reject known catastrophic outputs and return measurements for logging."""
    report = inspect_audio_quality(audio, sampling_rate)
    if report.has_stationary_mechanical_noise:
        raise AudioQualityError(
            "generated audio resembles stationary mechanical noise "
            f"(active={report.active_ratio:.3f}, rms_cv={report.rms_variation:.3f}, "
            f"flatness={report.spectral_flatness:.3f}, zcr={report.zero_crossing_rate:.3f})"
        )
    return report
