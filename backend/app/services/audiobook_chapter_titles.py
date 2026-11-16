"""Shared identities for EPUB chapter labels and audio track titles."""

import re

_CHAPTER_NUMBER_RE = re.compile(r"(?:^|\b)chapter\s+(\d+)\b|^\s*(\d+)\s*$", re.IGNORECASE)
_CREDITS_RE = re.compile(r"\b(?:opening|closing|end)\s+credits?\b", re.IGNORECASE)


def chapter_identity(title: str | None) -> tuple[str, int | str] | None:
    value = " ".join((title or "").split()).strip()
    if not value or _CREDITS_RE.search(value):
        return None
    # Publishers commonly decorate numeric TOC labels, e.g. "[ 12 ]".
    # Only unwrap a complete numeric label; part titles and dates are not chapters.
    decorated_number = re.fullmatch(r"\[\s*(\d+)\s*\]|\(\s*(\d+)\s*\)", value)
    if decorated_number:
        return "chapter", int(decorated_number.group(1) or decorated_number.group(2))
    if match := _CHAPTER_NUMBER_RE.search(value):
        return "chapter", int(match.group(1) or match.group(2))
    lowered = value.casefold()
    if "epilogue" in lowered:
        return "named", "epilogue"
    if "prologue" in lowered:
        return "named", "prologue"
    return "named", re.sub(r"[^a-z0-9]+", " ", lowered).strip()
