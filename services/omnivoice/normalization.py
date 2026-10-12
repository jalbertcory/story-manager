"""Pre-pass for OmniVoice's optional English text normalizer.

``OmniVoice.generate(normalize_text=True)`` delegates English to
WeTextProcessing, which handles most numbers, dates, and percentages well but
misreads two forms that are common in fiction:

* four-digit decades: ``1990s`` becomes "one thousand nine hundred and ninety
  seconds";
* dollar amounts with cents: ``$5.99`` becomes "five point nine nine dollars".

This module rewrites only those forms before the upstream normalizer runs.
"""

from __future__ import annotations

import re

_CENTURIES = {
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
    20: "twenty",
    21: "twenty-one",
}
_DECADES = {
    1: "tens",
    2: "twenties",
    3: "thirties",
    4: "forties",
    5: "fifties",
    6: "sixties",
    7: "seventies",
    8: "eighties",
    9: "nineties",
}

_DECADE_RE = re.compile(r"\b(1\d|2[01])(\d)0'?s\b")
_DOLLARS_AND_CENTS_RE = re.compile(r"\$(\d{1,3}(?:,\d{3})+|\d+)\.(\d{2})\b")


def _spell_decade(match: re.Match[str]) -> str:
    century = int(match.group(1))
    decade = int(match.group(2))
    if decade:
        return f"{_CENTURIES[century]} {_DECADES[decade]}"
    if century == 20:
        return "two thousands"
    return f"{_CENTURIES[century]} hundreds"


def _split_cents(match: re.Match[str]) -> str:
    dollars = match.group(1)
    cents = int(match.group(2))
    if not cents:
        return f"${dollars}"
    cents_text = f"{cents} cent" if cents == 1 else f"{cents} cents"
    if dollars == "0":
        return cents_text
    return f"${dollars} and {cents_text}"


def prepare_for_normalization(text: str) -> str:
    """Rewrite decades and cents so the upstream normalizer reads them correctly."""

    return _DOLLARS_AND_CENTS_RE.sub(_split_cents, _DECADE_RE.sub(_spell_decade, text))
