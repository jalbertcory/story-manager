import json
import math
from pathlib import Path
import wave

import numpy as np
import pytest

from services.omnivoice.audio_quality import AudioQualityError
from services.speaker_similarity import WESPEAKER_RESNET34, SpeakerVerifier
from services.voice_roster import (
    PROBE_TEXTS,
    SimilarityProfile,
    SpeakerCheck,
    SpeakerGuard,
    generate_checked,
    judge_speaker,
    load_profile,
    profile_from_scores,
    profile_path,
    save_profile,
)

RATE = 16_000
PROFILE = SimilarityProfile(model="m", mean=0.8, std=0.02, count=3)


def _voiced(frequency: float, seconds: float = 1.5) -> np.ndarray:
    """A pulsed harmonic tone that passes the generated-audio signal checks."""
    time = np.arange(round(seconds * RATE)) / RATE
    envelope = np.maximum(0, np.sin(2 * np.pi * 1.3 * time)) ** 2
    tone = 0.12 * np.sin(2 * np.pi * frequency * time) + 0.06 * np.sin(2 * np.pi * 2 * frequency * time)
    return (envelope * tone).astype(np.float32)


def _write_wav(path: Path, audio: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(np.clip(audio * 32767, -32768, 32767).astype("<i2").tobytes())
    return path


def _pitch_embedder(audio: np.ndarray) -> np.ndarray:
    """Embed a clip by its dominant pitch so different tones are different 'speakers'."""
    spectrum = np.abs(np.fft.rfft(audio))
    vector = np.zeros(40)
    vector[min(39, int(np.argmax(spectrum) * RATE / audio.size // 50))] = 1.0
    return vector + 0.01


def test_profile_from_scores_needs_two_finite_scores():
    assert profile_from_scores("m", [0.8]) is None
    assert profile_from_scores("m", [0.8, math.nan]) is None
    profile = profile_from_scores("m", [0.7, 0.8, 0.9])
    assert profile is not None
    assert profile.mean == pytest.approx(0.8)
    assert profile.std == pytest.approx(0.1)
    assert profile.count == 3


def test_profile_floor_uses_the_std_floor_for_unusually_consistent_probes():
    assert PROFILE.floor(3.0, std_floor=0.05) == pytest.approx(0.65)
    assert PROFILE.floor(3.0, std_floor=0.01) == pytest.approx(0.74)


def test_profiles_are_stored_per_verifier_next_to_the_sample(tmp_path):
    sample = tmp_path / "qwen3-abc.wav"
    save_profile(sample, SimilarityProfile(model="wespeaker", mean=0.8, std=0.05, count=3))
    save_profile(sample, SimilarityProfile(model="wavlm", mean=0.97, std=0.01, count=3))

    assert profile_path(sample) == tmp_path / "qwen3-abc.profile.json"
    assert set(json.loads(profile_path(sample).read_text())) == {"wespeaker", "wavlm"}
    assert load_profile(sample, "wespeaker") == SimilarityProfile(model="wespeaker", mean=0.8, std=0.05, count=3)
    assert load_profile(sample, "other") is None
    assert load_profile(tmp_path / "missing.wav", "wespeaker") is None


def test_judge_accepts_takes_within_the_voice_range():
    check = judge_speaker({"own": 0.7, "other": 0.3}, "own", profile=PROFILE, margin=3.0, std_floor=0.05)

    assert check.rejection is None
    assert check.similarity == 0.7
    assert check.slack == pytest.approx(0.05)


def test_judge_rejects_takes_below_the_drift_floor():
    check = judge_speaker({"own": 0.6}, "own", profile=PROFILE, margin=3.0, std_floor=0.05)

    assert check.rejection is not None and "drift floor 0.650" in check.rejection
    assert check.slack == pytest.approx(-0.05)


def test_judge_rejects_takes_closer_to_another_cast_voice():
    check = judge_speaker({"own": 0.7, "rival": 0.72}, "own", profile=PROFILE, margin=3.0, std_floor=0.05)

    assert check.rejection is not None and "closer to cast voice rival" in check.rejection
    assert check.slack == pytest.approx(-0.02)


def test_judge_cast_check_still_applies_before_a_voice_is_calibrated():
    check = judge_speaker({"own": 0.4, "rival": 0.5}, "own", profile=None, margin=3.0, std_floor=0.05)

    assert check.rejection is not None


@pytest.mark.parametrize("margin", [None, 0.0])
def test_judge_disabled_margin_skips_drift_and_cast_checks(margin):
    check = judge_speaker({"own": 0.1, "rival": 0.9}, "own", profile=PROFILE, margin=margin, std_floor=0.05)

    assert check == SpeakerCheck(similarity=0.1)


def test_judge_legacy_min_similarity_fails_hard():
    with pytest.raises(AudioQualityError, match="below 0.450"):
        judge_speaker({"own": 0.4}, "own", profile=None, margin=None, std_floor=0.05, min_similarity=0.45)


def test_judge_skips_unverifiable_takes():
    assert judge_speaker(None, "own", profile=PROFILE, margin=3.0, std_floor=0.05) == SpeakerCheck(similarity=None)


def _scripted(checks):
    outcomes = iter(checks)

    def check(_audio, _rate):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return check


def _numbered(attempt):
    return np.full(4, attempt, dtype=np.float32), RATE


def test_generate_checked_retries_until_a_take_passes():
    audio, _rate, check, attempts = generate_checked(
        _numbered,
        _scripted([SpeakerCheck(0.5, "drift", -0.1), AudioQualityError("noise"), SpeakerCheck(0.8)]),
        attempts=3,
        label="test",
    )

    assert attempts == 3
    assert audio[0] == 3
    assert check.rejection is None


def test_generate_checked_keeps_the_take_with_most_slack_when_all_drift():
    audio, _rate, check, attempts = generate_checked(
        _numbered,
        _scripted([SpeakerCheck(0.5, "drift", -0.2), SpeakerCheck(0.6, "drift", -0.05), AudioQualityError("noise")]),
        attempts=3,
        label="test",
    )

    assert attempts == 3
    assert audio[0] == 2
    assert check.slack == -0.05


def test_generate_checked_raises_when_no_take_is_usable():
    with pytest.raises(AudioQualityError, match="test failed quality validation after 2 attempts: noise"):
        generate_checked(
            _numbered, _scripted([AudioQualityError("hum"), AudioQualityError("noise")]), attempts=2, label="test"
        )


def test_generate_checked_counts_a_pregenerated_take_as_the_first_attempt():
    generated = []

    def generate(attempt):
        generated.append(attempt)
        return _numbered(attempt)

    audio, _rate, _check, attempts = generate_checked(
        generate,
        _scripted([SpeakerCheck(0.5, "drift", -0.1), SpeakerCheck(0.8)]),
        attempts=3,
        label="test",
        initial=(np.zeros(4, dtype=np.float32), RATE),
    )

    assert generated == [2]
    assert attempts == 2
    assert audio[0] == 2


class _Cast:
    """A fake voice store where each voice speaks at its own pitch."""

    def __init__(self, root: Path) -> None:
        self.pitches = {"low": 120.0, "mid": 300.0, "high": 700.0}
        self.samples = {voice: _write_wav(root / f"{voice}.wav", _voiced(pitch)) for voice, pitch in self.pitches.items()}
        self.probes: list[tuple[str, int]] = []

    def reference_path(self, voice_id: str) -> Path | None:
        if voice_id.startswith("preset:"):
            return None
        return self.samples[voice_id]

    def generate_probe(self, voice_id: str, text: str, seed: int) -> tuple[np.ndarray, int]:
        self.probes.append((text, seed))
        return _voiced(self.pitches[voice_id]), RATE


def _guard(cast: _Cast) -> SpeakerGuard:
    verifier = SpeakerVerifier(model_id=WESPEAKER_RESNET34, embedder=_pitch_embedder)
    return SpeakerGuard(cast.reference_path, cast.generate_probe, verifier=lambda: verifier)


def test_guard_calibrates_with_fixed_probes_and_persists_the_profile(tmp_path):
    cast = _Cast(tmp_path)
    guard = _guard(cast)

    profile = guard.calibrate("low")

    assert profile is not None and profile.count == len(PROBE_TEXTS)
    assert profile.mean == pytest.approx(1.0)
    assert [text for text, _seed in cast.probes] == list(PROBE_TEXTS)
    assert load_profile(cast.samples["low"], WESPEAKER_RESNET34) == profile

    fresh = _guard(cast)
    assert fresh.profile("low") == profile
    assert len(cast.probes) == len(PROBE_TEXTS), "stored profiles are not recalibrated"


def test_guard_lazily_calibrates_voices_created_before_profiles(tmp_path):
    cast = _Cast(tmp_path)
    guard = _guard(cast)

    guard.check("mid", _voiced(300.0), RATE, drift_margin=3.0)
    guard.check("mid", _voiced(300.0), RATE, drift_margin=3.0)

    assert len(cast.probes) == len(PROBE_TEXTS)


def test_guard_rejects_a_take_that_drifted_to_another_cast_voice(tmp_path):
    cast = _Cast(tmp_path)
    guard = _guard(cast)

    passing = guard.check("low", _voiced(120.0), RATE, drift_margin=3.0, cast_voice_ids=["mid", "high"])
    drifted = guard.check("low", _voiced(700.0), RATE, drift_margin=3.0, cast_voice_ids=["mid", "high", "low"])

    assert passing.rejection is None
    assert drifted.rejection is not None
    assert "drift floor" in drifted.rejection and "cast voice high" in drifted.rejection


def test_guard_ignores_presets_and_unknown_cast_voices(tmp_path):
    cast = _Cast(tmp_path)
    guard = _guard(cast)

    assert guard.cast_references("low", ["preset:Ryan", "missing", "low", "mid", "mid"]) == {"mid": cast.samples["mid"]}
    assert guard.check("preset:Ryan", _voiced(120.0), RATE, drift_margin=3.0) == SpeakerCheck(similarity=None)


def test_guard_without_margin_only_reports_similarity(tmp_path):
    cast = _Cast(tmp_path)
    guard = _guard(cast)

    check = guard.check("low", _voiced(700.0), RATE, cast_voice_ids=["high"])

    assert check.rejection is None
    assert check.similarity is not None and check.similarity < 0.1
    assert cast.probes == []
