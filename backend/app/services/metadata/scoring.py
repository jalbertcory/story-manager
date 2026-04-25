"""Text normalization and match scoring helpers for metadata providers."""

from difflib import SequenceMatcher
import re

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_SEPARATOR_RE = re.compile(r"[\s\-:,_]+")


def normalize_text(value: str) -> str:
    return _NON_ALNUM_RE.sub(" ", value.casefold()).strip()


def normalize_series(value: str) -> str:
    return _SEPARATOR_RE.sub(" ", value.casefold()).strip()


def title_similarity(left: str, right: str) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    return SequenceMatcher(a=left_norm, b=right_norm).ratio()
