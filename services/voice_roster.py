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

Voice design uses the same verifier to keep a new voice away from the rest of
the cast. When a designed sample lands too close to an existing voice, the next
attempt moves one description feature (pitch, texture, age, accent, pace) away
from that voice. If no attempt clears the limit, the most distinct candidate is
kept instead of failing or falling back to an unrelated preset.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
import logging
import math
from pathlib import Path
import re

import numpy as np

from services.omnivoice.audio_quality import AudioQualityError, validate_generated_audio
from services.speaker_similarity import SpeakerVerifier, get_speaker_verifier
from services.tts_consistency import seed_for_attempt

logger = logging.getLogger(__name__)

DEFAULT_DRIFT_MARGIN = 3.0
PROBE_TEXTS = (
    "The rain had stopped by the time we reached the old stone bridge at the edge of town.",
    "Honestly, I never expected him to say yes, but he laughed and handed me the keys.",
    "Count the crates twice, mark the broken ones, and bring the ledger back before dark.",
)
PROBE_SEED = 90_210
# Speaker embeddings of short clips score systematically lower against the
# reference than the ~5 s calibration probes (on OmniVoice, clips under 2.5 s
# averaged 1.9 std below the calibrated mean while clips over 5 s matched it).
# The drift floor therefore widens by SHORT_CLIP_SLOPE extra standard
# deviations per multiple of the probe length the clip falls short, up to
# SHORT_CLIP_MAX_EXTRA. The cast check does not depend on length and still
# applies in full to short clips.
SHORT_CLIP_SECONDS = 4.5
SHORT_CLIP_SLOPE = 1.5
SHORT_CLIP_MAX_EXTRA = 3.0
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


def short_clip_margin(seconds: float | None) -> float:
    """Extra standard deviations of drift margin for a clip of ``seconds``."""
    if not seconds or seconds >= SHORT_CLIP_SECONDS:
        return 0.0
    return min(SHORT_CLIP_MAX_EXTRA, SHORT_CLIP_SLOPE * (SHORT_CLIP_SECONDS / seconds - 1.0))


def judge_speaker(
    scores: Mapping[str, float] | None,
    voice_id: str,
    *,
    profile: SimilarityProfile | None,
    margin: float | None,
    std_floor: float,
    min_similarity: float | None = None,
    seconds: float | None = None,
) -> SpeakerCheck:
    """Apply the drift rules to precomputed verifier scores.

    ``scores`` holds the take's similarity to its own voice (``voice_id``) and
    to any cast voices. ``None`` means the take was too short to verify.
    ``min_similarity`` is the legacy absolute floor and fails hard.
    ``seconds`` is the take's length, used to relax the drift floor for
    clips shorter than the calibration probes.
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
        floor = profile.floor(margin + short_clip_margin(seconds), std_floor)
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
        profile = profile_from_scores(verifier.profile_key, scores)
        if profile is not None:
            save_profile(reference, profile)
            logger.info(
                "Calibrated %s with %s: similarity %.3f +/- %.3f over %d probes.",
                voice_id,
                verifier.profile_key,
                profile.mean,
                profile.std,
                profile.count,
            )
        else:
            logger.warning("Could not calibrate %s; only the cast check will apply.", voice_id)
        self._profiles[(voice_id, verifier.profile_key)] = profile
        return profile

    def profile(self, voice_id: str) -> SimilarityProfile | None:
        """Return the stored calibration, calibrating older voices on first use."""
        model = self._verifier().profile_key
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

    def roster_limit(self, requested: float | None) -> float:
        """Return the caller's roster limit, or the active verifier's calibrated one."""
        if requested is not None:
            return requested
        return self._verifier().calibration.roster_max_similarity

    def closest_voice(self, voice_ids: Sequence[str], audio: np.ndarray, rate: int) -> tuple[str | None, float | None]:
        """Return the stored voice in ``voice_ids`` that ``audio`` sounds most like."""
        references = self.cast_references("", voice_ids)
        scores = self._verifier().similarities(references, audio, rate) if references else None
        if not scores:
            return None, None
        closest = max(scores, key=scores.__getitem__)
        return closest, scores[closest]

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
            seconds=np.asarray(audio).size / rate if rate > 0 else None,
        )


# --- Roster distinctness for voice design ------------------------------------

# Retry order. Texture comes last: adding a rough timbre can contradict the
# requested character ("bright", "sweet") more than a pitch, age or accent step.
DESIGN_FEATURES = ("pitch", "age", "accent", "pace", "texture")
# Accents every local design model accepts for English speech.
ENGLISH_ACCENTS = ("american", "british", "australian", "canadian")
_PITCHES = ("very-low", "low", "medium", "high", "very-high")
_AGES = ("child", "teenager", "young-adult", "middle-aged", "elderly")
_PACES = ("slow", "normal", "fast")
_ALIASES = {
    "gender": {
        **dict.fromkeys(("woman", "women", "girl", "lady", "mother", "grandmother"), "female"),
        **dict.fromkeys(("man", "men", "boy", "gentleman", "father", "grandfather"), "male"),
    },
    "pitch": {"moderate": "medium", "very low": "very-low", "very high": "very-high"},
    "age": {
        "teen": "teenager",
        "young": "young-adult",
        "young adult": "young-adult",
        "middle": "middle-aged",
        "old": "elderly",
    },
    "pace": {},
}
_TAG_NAMES = {"pitch": "pitch", "age": "age", "accent": "accent", "pace": "speed"}
_TAG_RE = re.compile(r"\[([a-z]+)-([^\]]+)\]", re.IGNORECASE)
_PHRASES = {
    "gender": re.compile(
        r"\b(male|female|woman|women|girl|lady|mother|grandmother|man|men|boy|gentleman|father|grandfather)\b"
    ),
    "pitch": re.compile(r"\b(very[- ]low|low|moderate|medium|high|very[- ]high) pitch\b"),
    "age": re.compile(r"\b(child|teenager|teen|young[- ]adult|young|middle[- ]aged|elderly)\b"),
    "accent": re.compile(r"\b([a-z]+) accent\b"),
    "pace": re.compile(r"\b(slow|normal|fast) (?:speed|pace)\b"),
}
_ROUGH_RE = re.compile(r"\b(?:rasp\w*|gravel\w*|husk\w*|hoarse|gruff|rough|smok\w*|croak\w*)\b", re.IGNORECASE)
_ROUGH_PHRASE = "A raspy, gravelly voice."


def _normalize(feature: str, value: str) -> str:
    value = value.strip().lower().replace("_", "-")
    spaced = value.replace("-", " ")
    return _ALIASES.get(feature, {}).get(spaced, value.replace(" ", "-"))


def voice_features(description: str) -> dict[str, str]:
    """Read pitch, age, accent, pace and texture from a voice description.

    Accepts Story Manager tags (``[pitch-low]``) and the comma-separated
    phrases OmniVoice stores (``low pitch, british accent``).
    """
    tags = {name.lower(): value for name, value in _TAG_RE.findall(description)}
    prose = _TAG_RE.sub(" ", description).lower()
    features = {}
    for feature in ("gender", "pitch", "age", "accent", "pace"):
        value = tags.get(_TAG_NAMES.get(feature, feature))
        if value is None and (match := _PHRASES[feature].search(prose)):
            value = match.group(1)
        if value:
            features[feature] = _normalize(feature, value)
    if _ROUGH_RE.search(prose):
        features["texture"] = "rough"
    return features


def _step_away(levels: Sequence[str], ours: str | None, theirs: str | None, default: str) -> str | None:
    """Move one level away from ``theirs``; ``None`` when already apart at the edge."""
    own = levels.index(ours) if ours in levels else levels.index(default)
    rival = levels.index(theirs) if theirs in levels else levels.index(default)
    if own != rival:
        target = own + (1 if own > rival else -1)
        return levels[target] if 0 <= target < len(levels) else None
    direction = 1 if own >= len(levels) // 2 else -1
    target = own + direction
    if not 0 <= target < len(levels):
        target = own - direction
    return levels[target]


def _with_tag(description: str, name: str, value: str) -> str:
    tag = f"[{name}-{value}]"
    pattern = re.compile(rf"\[{name}-[^\]]+\]", re.IGNORECASE)
    if pattern.search(description):
        return pattern.sub(tag, description, count=1)
    tags = list(_TAG_RE.finditer(description))
    if not tags:
        return f"{tag} {description}".strip()
    end = tags[-1].end()
    return description[:end] + tag + description[end:]


def _tagged(description: str) -> str:
    """Express phrase-only descriptions as tags so added tags do not hide them."""
    if _TAG_RE.search(description):
        return description
    features = voice_features(description)
    tags = "".join(
        f"[{_TAG_NAMES.get(feature, feature)}-{features[feature]}]"
        for feature in ("gender", "age", "pitch", "accent", "pace")
        if feature in features
    )
    return f"{tags} {description}".strip()


def diverge_feature(description: str, rival: str, feature: str) -> str | None:
    """Move one ``feature`` of ``description`` away from ``rival``.

    Returns ``None`` when the feature is already distinct and cannot usefully
    move further. Gender is never changed.
    """
    ours, theirs = voice_features(description), voice_features(rival)
    if feature == "texture":
        if ours.get("texture") == "rough" or theirs.get("texture") == "rough":
            return None
        return f"{description.rstrip()} {_ROUGH_PHRASE}"
    value: str | None
    if feature == "accent":
        own_accent, rival_accent = ours.get("accent"), theirs.get("accent")
        if own_accent and own_accent != rival_accent:
            return None
        start = ENGLISH_ACCENTS.index(own_accent) + 1 if own_accent in ENGLISH_ACCENTS else 0
        rotated = ENGLISH_ACCENTS[start:] + ENGLISH_ACCENTS[:start]
        value = next(accent for accent in rotated if accent not in {own_accent, rival_accent})
    elif feature == "pitch":
        value = _step_away(_PITCHES, ours.get("pitch"), theirs.get("pitch"), "medium")
    elif feature == "age":
        levels = _AGES if ours.get("age") == "child" else _AGES[1:]
        value = _step_away(levels, ours.get("age"), theirs.get("age"), "young-adult")
    elif feature == "pace":
        value = _step_away(_PACES, ours.get("pace"), theirs.get("pace"), "normal")
    else:
        raise ValueError(f"unknown voice feature {feature!r}")
    if value is None:
        return None
    return _with_tag(_tagged(description), _TAG_NAMES[feature], value)


def diverge_profile(description: str, rival: str, features: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    """Apply the first feature in ``features`` that moves away from ``rival``.

    Returns the new description and the features still available for later
    retries, so each feature changes at most once per design.
    """
    for index, feature in enumerate(features):
        changed = diverge_feature(description, rival, feature)
        if changed is not None and changed != description:
            return changed, tuple(other for position, other in enumerate(features) if position != index)
    return description, tuple(features)


@dataclass(frozen=True)
class DesignCandidate:
    """A designed sample and how close it landed to the existing cast."""

    audio: np.ndarray
    rate: int
    voice: str
    attempt: int
    closest_voice_id: str | None = None
    similarity: float | None = None


def design_distinct_voice(
    render: Callable[[str, int | None], Audio],
    closest: Callable[[np.ndarray, int], tuple[str | None, float | None]],
    describe: Callable[[str], str | None],
    *,
    voice: str,
    seed: int | None,
    attempts: int,
    max_similarity: float | None,
    features: Sequence[str] = DESIGN_FEATURES,
    label: str = "voice design",
) -> DesignCandidate:
    """Design a voice that stays clear of the existing cast.

    ``render`` synthesizes the design sample for a description and seed,
    ``closest`` returns the nearest existing cast voice and its similarity,
    and ``describe`` returns a cast voice's stored description. ``features``
    lists the description features this model can express.
    """
    description = voice
    remaining = tuple(features)
    best: DesignCandidate | None = None
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        audio, rate = render(description, seed_for_attempt(seed, attempt))
        try:
            validate_generated_audio(audio, rate)
        except AudioQualityError as exc:
            last_error = exc
            logger.warning("Rejected %s on attempt %d/%d: %s", label, attempt, attempts, exc)
            continue
        rival_id, similarity = closest(audio, rate)
        candidate = DesignCandidate(audio, rate, description, attempt, rival_id, similarity)
        if max_similarity is None or similarity is None or similarity <= max_similarity:
            return candidate
        logger.warning(
            "Rejected %s on attempt %d/%d: %.3f similar to cast voice %s (limit %.3f)",
            label,
            attempt,
            attempts,
            similarity,
            rival_id,
            max_similarity,
        )
        if best is None or best.similarity is None or similarity < best.similarity:
            best = candidate
        rival = describe(rival_id) if rival_id else None
        if rival is not None:
            description, remaining = diverge_profile(description, rival, remaining)
    if best is not None:
        logger.warning(
            "Keeping the most distinct %s after %d attempts: %.3f similar to %s",
            label,
            attempts,
            best.similarity,
            best.closest_voice_id,
        )
        return best
    raise AudioQualityError(f"{label} produced no usable audio after {attempts} attempts: {last_error}") from last_error
