import json
import math
from pathlib import Path
import threading
import wave

import numpy as np
import pytest

from services.omnivoice.audio_quality import AudioQualityError
from services.speaker_similarity import CALIBRATIONS, PINNED_REVISIONS, WESPEAKER_RESNET34, SpeakerVerifier
from services.voice_roster import (
    DESIGN_FEATURES,
    PROBE_TEXTS,
    SHORT_CLIP_MAX_EXTRA,
    SimilarityProfile,
    SpeakerCheck,
    SpeakerGuard,
    design_distinct_voice,
    diverge_feature,
    diverge_profile,
    generate_checked,
    judge_speaker,
    load_profile,
    profile_from_scores,
    profile_path,
    save_profile,
    short_clip_margin,
    voice_features,
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
    assert profile.std == pytest.approx(1.4826 * 0.1)
    assert profile.count == 3


def test_one_bad_probe_cannot_disable_the_drift_check():
    wespeaker = CALIBRATIONS["wespeaker"]
    profile = profile_from_scores("m", [0.72, 0.70, 0.35])
    assert profile is not None
    # A plain mean and std (0.59 +/- 0.21) put the floor near -0.04.
    floor = profile.floor(3.0, wespeaker.drift_std_floor, wespeaker.drift_std_max)
    assert profile.mean == pytest.approx(0.70)
    assert floor == pytest.approx(0.55)
    assert judge_speaker({"self": 0.36}, "self", profile=profile, margin=3.0, std_floor=wespeaker.drift_std_floor).rejection


def test_profile_floor_clamps_the_spread():
    assert PROFILE.floor(3.0, std_floor=0.05) == pytest.approx(0.65)
    assert PROFILE.floor(3.0, std_floor=0.01) == pytest.approx(0.74)
    wide = SimilarityProfile(model="m", mean=0.59, std=0.21, count=3)
    assert wide.floor(3.0, std_floor=0.05, std_max=0.1) == pytest.approx(0.29)


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


def test_short_clips_get_a_wider_drift_floor():
    assert short_clip_margin(None) == 0.0
    assert short_clip_margin(6.0) == 0.0
    assert 0.0 < short_clip_margin(3.0) < short_clip_margin(2.0) < short_clip_margin(1.0)
    assert short_clip_margin(0.2) == SHORT_CLIP_MAX_EXTRA

    scores = {"own": 0.63}
    assert judge_speaker(scores, "own", profile=PROFILE, margin=3.0, std_floor=0.05, seconds=6.0).rejection
    assert judge_speaker(scores, "own", profile=PROFILE, margin=3.0, std_floor=0.05, seconds=2.0).rejection is None


def test_short_clips_still_fail_the_cast_check():
    check = judge_speaker({"own": 0.5, "rival": 0.55}, "own", profile=PROFILE, margin=3.0, std_floor=0.05, seconds=1.0)

    assert check.rejection is not None and "closer to cast voice rival" in check.rejection


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
    assert load_profile(cast.samples["low"], f"{WESPEAKER_RESNET34}@{PINNED_REVISIONS[WESPEAKER_RESNET34]}") == profile

    fresh = _guard(cast)
    assert fresh.profile("low") == profile
    assert len(cast.probes) == len(PROBE_TEXTS), "stored profiles are not recalibrated"


def test_guard_recalibrates_when_the_verifier_weights_change(tmp_path):
    cast = _Cast(tmp_path)
    _guard(cast).calibrate("low")
    other_weights = SpeakerVerifier(model_id=WESPEAKER_RESNET34, embedder=_pitch_embedder, revision="0" * 40)
    guard = SpeakerGuard(cast.reference_path, cast.generate_probe, verifier=lambda: other_weights)

    guard.profile("low")

    assert len(cast.probes) == 2 * len(PROBE_TEXTS)


def test_concurrent_profile_saves_never_share_a_temporary_file(tmp_path):
    sample = _write_wav(tmp_path / "voice.wav", _voiced(200.0))
    errors: list[BaseException] = []

    def save(index: int) -> None:
        try:
            for _ in range(25):
                save_profile(sample, SimilarityProfile(model=f"m{index}", mean=0.8, std=0.02, count=3))
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert json.loads(profile_path(sample).read_text())
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_eager_calibration_is_retried_on_first_use(tmp_path):
    cast = _Cast(tmp_path)
    working_probe = cast.generate_probe

    def broken_probe(voice_id: str, text: str, seed: int) -> tuple[np.ndarray, int]:
        raise RuntimeError("model busy")

    guard = SpeakerGuard(
        cast.reference_path,
        lambda *args: probe(*args),
        verifier=lambda: SpeakerVerifier(model_id=WESPEAKER_RESNET34, embedder=_pitch_embedder),
    )
    probe = broken_probe
    assert guard.try_calibrate("low") is None

    probe = working_probe
    assert guard.profile("low") is not None
    assert len(cast.probes) == len(PROBE_TEXTS)


def test_concurrent_first_use_calibrates_a_voice_once(tmp_path):
    cast = _Cast(tmp_path)
    guard = _guard(cast)
    threads = [threading.Thread(target=guard.profile, args=("mid",)) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(cast.probes) == len(PROBE_TEXTS)


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


def test_guard_roster_limit_defaults_to_the_verifier_calibration(tmp_path):
    guard = _guard(_Cast(tmp_path))

    assert guard.roster_limit(None) == pytest.approx(0.45)
    assert guard.roster_limit(0.3) == 0.3


def test_guard_finds_the_closest_stored_voice(tmp_path):
    cast = _Cast(tmp_path)
    guard = _guard(cast)

    closest, similarity = guard.closest_voice(["low", "high", "preset:Ryan"], _voiced(700.0), RATE)

    assert closest == "high"
    assert similarity == pytest.approx(1.0)
    assert guard.closest_voice([], _voiced(700.0), RATE) == (None, None)


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        (
            "[gender-female][age-young-adult][pitch-high][speed-fast] A bright voice.",
            {"gender": "female", "age": "young-adult", "pitch": "high", "pace": "fast"},
        ),
        (
            "male, middle-aged, very low pitch, british accent",
            {"gender": "male", "age": "middle-aged", "pitch": "very-low", "accent": "british"},
        ),
        ("A gravelly old fisherman, slow pace.", {"pace": "slow", "texture": "rough"}),
        ("A warm young woman narrator.", {"gender": "female", "age": "young-adult"}),
    ],
)
def test_voice_features_read_tags_and_phrases(description, expected):
    assert voice_features(description) == expected


def test_diverge_feature_moves_away_from_the_rival():
    ours = "[gender-female][pitch-high] Bright."

    assert diverge_feature(ours, "female, high pitch", "pitch") == "[gender-female][pitch-very-high] Bright."
    assert diverge_feature(ours, "female, very high pitch", "pitch") == "[gender-female][pitch-medium] Bright."
    assert diverge_feature("[pitch-very-high]", "high pitch", "pitch") is None, "already apart at the edge"
    assert diverge_feature(ours, "female, medium pitch", "pitch") == "[gender-female][pitch-very-high] Bright."
    assert diverge_feature(ours, "female, high pitch", "texture") == f"{ours} A raspy, gravelly voice."
    assert diverge_feature(ours, "female, raspy voice", "texture") is None


def test_diverge_feature_keeps_accents_english_and_gender_fixed():
    ours = "[gender-male][accent-british] Calm."

    assert diverge_feature(ours, "male, british accent", "accent") == "[gender-male][accent-australian] Calm."
    assert diverge_feature(ours, "male, american accent", "accent") is None
    changed = diverge_feature("A calm young man.", "male, american accent", "accent")
    assert changed is not None
    assert voice_features(changed)["accent"] == "british"
    assert voice_features(changed)["gender"] == "male", "phrase-only descriptions keep their gender as a tag"


def test_diverge_feature_does_not_turn_adults_into_children():
    assert voice_features(diverge_feature("[age-teenager]", "teenager", "age") or "")["age"] == "young-adult"
    assert voice_features(diverge_feature("[age-child]", "child", "age") or "")["age"] == "teenager"


def test_diverge_profile_changes_each_feature_once():
    rival = "female, young adult, high pitch, american accent"
    first, remaining = diverge_profile("[gender-female][pitch-high] Bright.", rival, ("pitch", "age"))
    second, remaining = diverge_profile(first, rival, remaining)

    assert first == "[gender-female][pitch-very-high] Bright."
    assert voice_features(second)["age"] != "young-adult"
    assert remaining == ()
    assert diverge_profile(second, rival, remaining) == (second, ())


class _Designer:
    """Render each description as a tone and score it by scripted similarities."""

    def __init__(self, similarities, failures=()):
        self.similarities = list(similarities)
        self.failures = set(failures)
        self.rendered: list[tuple[str, int | None]] = []

    def render(self, description, seed):
        self.rendered.append((description, seed))
        if len(self.rendered) in self.failures:
            return np.zeros(RATE, dtype=np.float32), RATE
        return _voiced(200.0 + 50 * len(self.rendered)), RATE

    def closest(self, _audio, _rate):
        return "rival", self.similarities.pop(0)


def _design(designer, **kwargs):
    options = {"voice": "[gender-female][pitch-high] Bright.", "seed": 10, "attempts": 4, "max_similarity": 0.45}
    options.update(kwargs)
    return design_distinct_voice(
        designer.render, designer.closest, lambda _voice_id: "female, high pitch, american accent", **options
    )


def test_design_accepts_a_distinct_first_take():
    designer = _Designer([0.3])

    candidate = _design(designer)

    assert candidate.attempt == 1
    assert candidate.voice == "[gender-female][pitch-high] Bright."
    assert candidate.similarity == 0.3


def test_design_diverges_from_the_closest_voice_until_distinct():
    designer = _Designer([0.6, 0.5, 0.4])

    candidate = _design(designer, features=("pitch", "accent"))

    assert candidate.attempt == 3
    assert [voice for voice, _seed in designer.rendered] == [
        "[gender-female][pitch-high] Bright.",
        "[gender-female][pitch-very-high] Bright.",
        "[gender-female][pitch-very-high][accent-british] Bright.",
    ]
    assert len({seed for _voice, seed in designer.rendered}) == 3
    assert candidate.voice == designer.rendered[-1][0]


def test_design_changes_texture_only_after_the_other_features():
    designer = _Designer([0.6, 0.6, 0.6, 0.6, 0.6, 0.4])

    candidate = _design(designer, attempts=6, features=DESIGN_FEATURES)

    assert candidate.attempt == 6
    assert "raspy" not in designer.rendered[4][0]
    assert candidate.voice.endswith("A raspy, gravelly voice.")


def test_design_keeps_the_most_distinct_take_when_none_clears_the_limit():
    designer = _Designer([0.7, 0.55, 0.6])

    candidate = _design(designer, attempts=3)

    assert candidate.attempt == 2
    assert candidate.similarity == 0.55
    assert candidate.voice == designer.rendered[1][0]


def test_design_retries_unusable_audio_and_fails_without_any():
    designer = _Designer([0.2], failures={1})
    assert _design(designer).attempt == 2

    with pytest.raises(AudioQualityError, match="no usable audio after 2 attempts"):
        _design(_Designer([], failures={1, 2}), attempts=2)


def test_design_without_a_cast_accepts_the_first_usable_take():
    designer = _Designer([None])

    assert _design(designer).attempt == 1
