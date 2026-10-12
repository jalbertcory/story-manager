"""Speaker drift and cast-distinctness rules shared by local TTS adapters.

Every stored voice is calibrated once by synthesizing a few probe sentences
through the normal clone path and scoring them against the voice's own
enrollment sample. That gives the voice's ordinary similarity range, so drift
is judged relative to the voice instead of against one absolute cosine
threshold that means different things for different voices and verifiers.

A generated line is rejected and retried when it falls more than ``margin``
standard deviations below its voice's probe mean, or when it scores at least
as close to another voice in the cast as to its own. If every attempt is
rejected for those reasons, the take with the most slack is kept rather than
failing the whole sentence.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
import logging
import math
from pathlib import Path

import numpy as np

from services.omnivoice.audio_quality import AudioQualityError, validate_generated_audio
from services.speaker_similarity import SpeakerVerifier, get_speaker_verifier

logger = logging.getLogger(__name__)

DEFAULT_DRIFT_MARGIN = 3.0
PROBE_TEXTS = (
    "The rain had stopped by the time we reached the old stone bridge at the edge of town.",
    "Honestly, I never expected him to say yes, but he laughed and handed me the keys.",
    "Count the crates twice, mark the broken ones, and bring the ledger back before dark.",
)
PROBE_SEED = 90_210
_PROFILE_SUFFIX = ".profile.json"

Audio = tuple[np.ndarray, int]


@dataclass(frozen=True)
class SimilarityProfile:
    """How closely a voice's own generations normally match its enrollment."""

    model: str
    mean: float
    std: float
    count: int

    def floor(self, margin: float, std_floor: float) -> float:
        return self.mean - margin * max(self.std, std_floor)


def profile_from_scores(model: str, scores: Iterable[float]) -> SimilarityProfile | None:
    values = np.asarray([score for score in scores if math.isfinite(score)], dtype=np.float64)
    if values.size < 2:
        return None
    return SimilarityProfile(model=model, mean=float(values.mean()), std=float(values.std(ddof=1)), count=int(values.size))


def profile_path(sample_path: Path) -> Path:
    return sample_path.with_name(sample_path.stem + _PROFILE_SUFFIX)


def load_profile(sample_path: Path, model: str) -> SimilarityProfile | None:
    """Read the calibration for ``model``; other verifiers' entries are ignored."""
    try:
        entries = json.loads(profile_path(sample_path).read_text(encoding="utf-8"))
        entry = entries[model]
        return SimilarityProfile(model=model, mean=float(entry["mean"]), std=float(entry["std"]), count=int(entry["count"]))
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return None


def save_profile(sample_path: Path, profile: SimilarityProfile) -> None:
    path = profile_path(sample_path)
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(entries, dict):
            entries = {}
    except (FileNotFoundError, ValueError):
        entries = {}
    entries[profile.model] = {"mean": profile.mean, "std": profile.std, "count": profile.count}
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True)
class SpeakerCheck:
    """Outcome of comparing one take with its own voice and the rest of the cast."""

    similarity: float | None
    rejection: str | None = None
    # Distance from the nearest rejection boundary; larger is safer. Used to
    # pick the least-bad take when every attempt is rejected.
    slack: float = math.inf


def judge_speaker(
    scores: Mapping[str, float] | None,
    voice_id: str,
    *,
    profile: SimilarityProfile | None,
    margin: float | None,
    std_floor: float,
    min_similarity: float | None = None,
) -> SpeakerCheck:
    """Apply the drift rules to precomputed verifier scores.

    ``scores`` holds the take's similarity to its own voice (``voice_id``) and
    to any cast voices. ``None`` means the take was too short to verify.
    ``min_similarity`` is the legacy absolute floor and fails hard.
    """
    if scores is None or voice_id not in scores:
        return SpeakerCheck(similarity=None)
    similarity = scores[voice_id]
    if min_similarity is not None and similarity < min_similarity:
        raise AudioQualityError(f"speaker similarity {similarity:.3f} is below {min_similarity:.3f}")
    if not margin:
        return SpeakerCheck(similarity=similarity)

    reasons = []
    slack = math.inf
    if profile is not None:
        floor = profile.floor(margin, std_floor)
        slack = similarity - floor
        if similarity < floor:
            reasons.append(f"speaker similarity {similarity:.3f} is below this voice's drift floor {floor:.3f}")
    others = {key: value for key, value in scores.items() if key != voice_id}
    if others:
        closest = max(others, key=others.__getitem__)
        cast_slack = similarity - others[closest]
        slack = min(slack, cast_slack)
        if cast_slack <= 0:
            reasons.append(
                f"take sounds closer to cast voice {closest} ({others[closest]:.3f}) than its own ({similarity:.3f})"
            )
    return SpeakerCheck(similarity=similarity, rejection="; ".join(reasons) or None, slack=slack)


def generate_checked(
    generate: Callable[[int], Audio],
    check: Callable[[np.ndarray, int], SpeakerCheck],
    *,
    attempts: int,
    label: str,
    initial: Audio | None = None,
) -> tuple[np.ndarray, int, SpeakerCheck, int]:
    """Generate until a take passes, keeping the best soft-rejected take.

    ``check`` raises :class:`AudioQualityError` for unusable audio (signal
    faults, legacy similarity floor) and returns a rejection reason for speaker
    drift. ``initial`` is an already generated first attempt, such as one item
    of a native batch. Returns the take, its check and the attempts used.
    """
    best: tuple[np.ndarray, int, SpeakerCheck] | None = None
    last_error: Exception | None = None
    used = 0
    for attempt in range(1, max(1, attempts) + 1):
        audio, rate = initial if attempt == 1 and initial is not None else generate(attempt)
        used = attempt
        try:
            result = check(audio, rate)
        except AudioQualityError as exc:
            last_error = exc
            logger.warning("Rejected %s on attempt %d/%d: %s", label, attempt, attempts, exc)
            continue
        if result.rejection is None:
            return audio, rate, result, attempt
        logger.warning("Rejected %s on attempt %d/%d: %s", label, attempt, attempts, result.rejection)
        if best is None or result.slack > best[2].slack:
            best = (audio, rate, result)
    if best is not None:
        logger.warning("Keeping the closest %s take after %d attempts: %s", label, used, best[2].rejection)
        return best[0], best[1], best[2], used
    raise AudioQualityError(f"{label} failed quality validation after {used} attempts: {last_error}") from last_error


class SpeakerGuard:
    """Per-runtime drift checks with persisted probe calibrations.

    ``reference_path`` maps a voice ID to its enrollment WAV, returning
    ``None`` for voices without one (built-in presets) and raising
    ``KeyError``/``ValueError`` for unknown voices. ``generate_probe`` renders
    probe text with a stored voice and seed. ``calibratable`` limits which
    voices may have a profile written next to their enrollment sample.
    """

    def __init__(
        self,
        reference_path: Callable[[str], Path | None],
        generate_probe: Callable[[str, str, int], Audio],
        *,
        calibratable: Callable[[str], bool] = lambda _voice_id: True,
        verifier: Callable[[], SpeakerVerifier] = get_speaker_verifier,
    ) -> None:
        self._reference_path = reference_path
        self._generate_probe = generate_probe
        self._calibratable = calibratable
        self._verifier = verifier
        self._profiles: dict[tuple[str, str], SimilarityProfile | None] = {}

    def calibrate(self, voice_id: str) -> SimilarityProfile | None:
        """Synthesize the probe sentences and persist the voice's own range."""
        reference = self._reference_path(voice_id)
        if reference is None or not self._calibratable(voice_id):
            return None
        verifier = self._verifier()
        scores = []
        for index, text in enumerate(PROBE_TEXTS):
            audio, rate = self._generate_probe(voice_id, text, PROBE_SEED + index)
            try:
                validate_generated_audio(audio, rate)
            except AudioQualityError as exc:
                logger.warning("Skipping unusable calibration probe %d for %s: %s", index + 1, voice_id, exc)
                continue
            score = verifier.similarity(voice_id, reference, audio, rate)
            if score is not None:
                scores.append(score)
        profile = profile_from_scores(verifier.model_id, scores)
        if profile is not None:
            save_profile(reference, profile)
            logger.info(
                "Calibrated %s with %s: similarity %.3f +/- %.3f over %d probes.",
                voice_id,
                verifier.model_id,
                profile.mean,
                profile.std,
                profile.count,
            )
        else:
            logger.warning("Could not calibrate %s; only the cast check will apply.", voice_id)
        self._profiles[(voice_id, verifier.model_id)] = profile
        return profile

    def profile(self, voice_id: str) -> SimilarityProfile | None:
        """Return the stored calibration, calibrating older voices on first use."""
        model = self._verifier().model_id
        key = (voice_id, model)
        if key in self._profiles:
            return self._profiles[key]
        reference = self._reference_path(voice_id)
        profile = load_profile(reference, model) if reference is not None else None
        if profile is None:
            return self.calibrate(voice_id)
        self._profiles[key] = profile
        return profile

    def cast_references(self, voice_id: str, cast_voice_ids: Sequence[str]) -> dict[str, Path]:
        references = {}
        for cast_id in dict.fromkeys(cast_voice_ids):
            if cast_id == voice_id:
                continue
            try:
                reference = self._reference_path(cast_id)
            except (KeyError, ValueError):
                logger.warning("Ignoring unknown cast voice %s in drift check.", cast_id)
                continue
            if reference is not None:
                references[cast_id] = reference
        return references

    def check(
        self,
        voice_id: str | None,
        audio: np.ndarray,
        rate: int,
        *,
        drift_margin: float | None = None,
        cast_voice_ids: Sequence[str] = (),
        min_similarity: float | None = None,
    ) -> SpeakerCheck:
        reference = self._reference_path(voice_id) if voice_id else None
        if voice_id is None or reference is None:
            return SpeakerCheck(similarity=None)
        verifier = self._verifier()
        references = {voice_id: reference}
        profile = None
        if drift_margin:
            references.update(self.cast_references(voice_id, cast_voice_ids))
            profile = self.profile(voice_id)
        return judge_speaker(
            verifier.similarities(references, audio, rate),
            voice_id,
            profile=profile,
            margin=drift_margin,
            std_floor=verifier.calibration.drift_std_floor,
            min_similarity=min_similarity,
        )
