"""Translate Story Manager voice tags into official OmniVoice arguments."""

from __future__ import annotations

import re
from dataclasses import dataclass

_VOICE_TAG_RE = re.compile(r"\[([a-z]+)-([^\]]+)\]", re.IGNORECASE)
_TEXT_TAG_RE = re.compile(r"\[([a-z][a-z-]*)\]", re.IGNORECASE)

_SUPPORTED_NONVERBAL_TAGS = {
    "confirmation-en",
    "dissatisfaction-hnn",
    "laughter",
    "question-ah",
    "question-ei",
    "question-en",
    "question-oh",
    "question-yi",
    "sigh",
    "surprise-ah",
    "surprise-oh",
    "surprise-wa",
    "surprise-yo",
}

_PITCH = {
    "very-low": "very low pitch",
    "low": "low pitch",
    "medium": "moderate pitch",
    "moderate": "moderate pitch",
    "high": "high pitch",
    "very-high": "very high pitch",
}
_AGE = {
    "child": "child",
    "teen": "teenager",
    "teenager": "teenager",
    "young": "young adult",
    "young-adult": "young adult",
    "middle": "middle-aged",
    "middle-aged": "middle-aged",
    "old": "elderly",
    "elderly": "elderly",
}
_SPEED = {"slow": 0.85, "normal": 1.0, "fast": 1.15}


@dataclass(frozen=True)
class GenerationPrompt:
    text: str
    instruct: str | None
    speed: float


def translate_generation_prompt(voice: str | None, text: str) -> GenerationPrompt:
    """Return official ``instruct``/``speed`` values and supported inline tags.

    Story Manager originally stored compact tags such as ``[pitch-low]``.
    OmniVoice 0.2 expects comma-separated attributes such as ``low pitch``.
    Existing profiles remain valid through this translation layer.
    """

    attributes: dict[str, str] = {}
    speed = 1.0
    raw_voice = (voice or "").strip()

    matches = list(_VOICE_TAG_RE.finditer(raw_voice))
    if matches:
        for match in matches:
            category = match.group(1).lower()
            value = match.group(2).lower().strip()
            if category == "gender" and value in {"male", "female"}:
                attributes["gender"] = value
            elif category == "pitch" and value in _PITCH:
                attributes["pitch"] = _PITCH[value]
            elif category == "age" and value in _AGE:
                attributes["age"] = _AGE[value]
            elif category == "accent" and value:
                attributes["accent"] = f"{value} accent"
            elif category == "style" and value == "whisper":
                attributes["style"] = "whisper"
            elif category == "speed" and value in _SPEED:
                speed = _SPEED[value]
    elif raw_voice:
        # Also accept native OmniVoice instructions for new/manual profiles.
        attributes["native"] = raw_voice

    def replace_text_tag(match: re.Match[str]) -> str:
        tag = match.group(1).lower()
        if tag in _SUPPORTED_NONVERBAL_TAGS:
            return f"[{tag}]"
        if tag == "whisper":
            attributes["style"] = "whisper"
        # Story Manager historically offered tags such as [shout] that are not
        # accepted by OmniVoice. Remove them instead of failing the whole book.
        return ""

    normalized_text = re.sub(r"\s+", " ", _TEXT_TAG_RE.sub(replace_text_tag, text)).strip()
    instruct = ", ".join(attributes.values()) or None
    return GenerationPrompt(text=normalized_text, instruct=instruct, speed=speed)
