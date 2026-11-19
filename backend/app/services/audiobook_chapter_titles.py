"""Shared identities for EPUB chapter labels and audio track titles."""

import re

_CREDITS_RE = re.compile(r"\b(?:opening|closing|end)\s+credits?\b", re.IGNORECASE)

_ONES = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_NUMBER_WORD = "|".join([*_ONES, *_TENS, "hundred"])
# "Twenty-Eight", "One Hundred and Five"; parsed and checked by _spelled_number.
_SPELLED_NUMBER = rf"(?:{_NUMBER_WORD})(?:(?:\s+|-)(?:and\s+)?(?:{_NUMBER_WORD}))*"
_ROMAN_NUMERAL_RE = re.compile(r"M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})")
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

# "Chapter 12", "Chapter IV" (upper case only, so words are not read as
# numerals), "Chapter Twenty-One: Subtitle".
_CHAPTER_LABEL_RE = re.compile(
    rf"\bchapter\s+(?:(?P<digits>\d+)|(?-i:(?P<roman>[IVXLCDM]+))|(?P<words>{_SPELLED_NUMBER}))\b",
    re.IGNORECASE,
)
_DECORATED_NUMBER_RE = re.compile(r"\[\s*(\d+)\s*\]|\(\s*(\d+)\s*\)")
# A whole title that is only a number, or a number, a separator and a subtitle:
# "12", "12. Title", "12: Title", "Twelve", "Twelve - Title". A separator is
# required before a subtitle so "7 Days Later" or "One Last Thing" stay named,
# and digits before a subtitle are capped at three so years stay named.
_SEPARATOR = r"\s*[.:)\-–—]\s+\S"
_BARE_NUMBER_RE = re.compile(r"\d+")
_NUMBERED_TITLE_RE = re.compile(rf"(?P<number>\d{{1,3}}){_SEPARATOR}")
_SPELLED_TITLE_RE = re.compile(rf"(?P<number>{_SPELLED_NUMBER})(?:{_SEPARATOR}.*)?", re.IGNORECASE)


def _spelled_number(text: str) -> int | None:
    tokens = [token for token in re.split(r"[\s-]+", text.casefold()) if token and token != "and"]
    value = 0
    if len(tokens) >= 2 and tokens[1] == "hundred":
        if _ONES.get(tokens[0], 10) >= 10:
            return None
        value = _ONES[tokens[0]] * 100
        tokens = tokens[2:]
    if tokens and tokens[0] in _TENS:
        value += _TENS[tokens.pop(0)]
        if tokens and _ONES.get(tokens[0], 10) < 10:
            value += _ONES[tokens.pop(0)]
    elif tokens and tokens[0] in _ONES:
        value += _ONES[tokens.pop(0)]
    return value if value and not tokens else None


def _roman_number(text: str) -> int | None:
    if not _ROMAN_NUMERAL_RE.fullmatch(text):
        return None
    total = 0
    for index, character in enumerate(text):
        value = _ROMAN_VALUES[character]
        following = _ROMAN_VALUES[text[index + 1]] if index + 1 < len(text) else 0
        total += -value if value < following else value
    return total or None


def _chapter_label_number(match: re.Match[str]) -> int | None:
    if match.group("digits"):
        return int(match.group("digits"))
    if match.group("roman"):
        return _roman_number(match.group("roman"))
    return _spelled_number(match.group("words"))


def _title_number(value: str) -> int | None:
    decorated = _DECORATED_NUMBER_RE.fullmatch(value)
    if decorated:
        return int(decorated.group(1) or decorated.group(2))
    if (label := _CHAPTER_LABEL_RE.search(value)) and (number := _chapter_label_number(label)) is not None:
        return number
    if _BARE_NUMBER_RE.fullmatch(value):
        return int(value)
    if numbered := _NUMBERED_TITLE_RE.match(value):
        return int(numbered.group("number"))
    if spelled := _SPELLED_TITLE_RE.fullmatch(value):
        return _spelled_number(spelled.group("number"))
    return None


def chapter_identity(title: str | None) -> tuple[str, int | str] | None:
    """Identify a chapter label so EPUB chapters and audio tracks can be paired.

    Numbered labels compare by number whatever their spelling ("Chapter 12",
    "[ 12 ]", "12. Title", "Twelve", "Chapter XII"); anything else compares by
    its normalized text. Credits have no chapter.
    """
    value = " ".join((title or "").split()).strip()
    if not value or _CREDITS_RE.search(value):
        return None
    # Only a complete numeric label or a chapter label counts; part titles,
    # dates and decorated numbers inside longer titles stay named.
    if (number := _title_number(value)) is not None:
        return "chapter", number
    lowered = value.casefold()
    if "epilogue" in lowered:
        return "named", "epilogue"
    if "prologue" in lowered:
        return "named", "prologue"
    return "named", re.sub(r"[^a-z0-9]+", " ", lowered).strip()
