"""Small deterministic controls shared by local TTS adapters."""

from __future__ import annotations

import os
import re

MIN_SPEAKER_VERIFICATION_SECONDS = float(os.getenv("SPEAKER_VERIFIER_MIN_SECONDS", "1.0"))
_PROFILE_TOKEN_RE = re.compile(r"\[([a-z]+)-([^\]]+)\]", re.IGNORECASE)


def candidate_has_enough_speech(sample_count: int, sampling_rate: int) -> bool:
    """Return whether an utterance is long enough for a meaningful speaker score."""
    if sampling_rate <= 0:
        raise ValueError("sampling rate must be positive")
    return sample_count >= round(sampling_rate * MIN_SPEAKER_VERIFICATION_SECONDS)


def seed_for_attempt(seed: int | None, attempt: int) -> int | None:
    """Return a reproducible but distinct seed for a one-based retry attempt."""
    if seed is None:
        return None
    if attempt < 1:
        raise ValueError("attempt must be at least 1")
    return (seed + attempt - 1) & 0x7FFFFFFF


def voice_instruction(profile: str | None) -> str:
    """Translate profile tokens while preserving free-form acoustic detail."""
    profile = (profile or "").strip()
    tokens = {name.lower(): value.strip() for name, value in _PROFILE_TOKEN_RE.findall(profile)}
    if not tokens:
        return profile
    phrases = []
    for name in ("gender", "age", "pitch", "accent", "style", "speed"):
        if value := tokens.get(name):
            phrases.append(f"{value.replace('-', ' ')} {name}")
    remaining = _PROFILE_TOKEN_RE.sub("", profile).strip()
    if remaining:
        phrases.append(remaining)
    return ", ".join(phrases)
