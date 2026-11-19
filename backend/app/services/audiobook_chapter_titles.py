"""Shared identities for EPUB chapter labels and audio track titles."""

import re
from dataclasses import dataclass
from functools import lru_cache

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
# Hyphen, en dash and em dash, escaped for use inside a character class.
_DASH = "\\-\u2013\u2014"
# "Twenty-Eight", "Thirty – Seven", "One Hundred and Five"; parsed and checked
# by _spelled_number.
_SPELLED_NUMBER = rf"(?:{_NUMBER_WORD})(?:(?:\s*[{_DASH}]\s*|\s+)(?:and\s+)?(?:{_NUMBER_WORD}))*"
# A number word or numeral ends a word: "Twenty-First" and "I'm" are not numbers.
_WORD_END = rf"(?![\w'’]|[{_DASH}]\w)"
_ROMAN_NUMERAL_RE = re.compile(r"M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})")
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
# Higher "numerals" in all-caps titles are words ("CHAPTER MIX"), not chapters.
_MAX_ROMAN_CHAPTER = 399

# "Chapter 12", "Chapter IV" (upper case only, so words are not read as
# numerals), "Chapter Twenty-One: Subtitle".
_CHAPTER_LABEL_RE = re.compile(
    rf"\bchapter\s+(?:(?P<digits>\d+)\b|(?:(?-i:(?P<roman>[IVXLCDM]+))|(?P<words>{_SPELLED_NUMBER})){_WORD_END})",
    re.IGNORECASE,
)
_DECORATED_NUMBER_RE = re.compile(r"\[\s*(\d+)\s*\]|\(\s*(\d+)\s*\)")
# A whole title that is only a number, or a number, a separator and a subtitle:
# "12", "12. Title", "12: Title", "Twelve", "Twelve - Title". A separator is
# required before a subtitle so "7 Days Later" or "One Last Thing" stay named,
# and digits before a subtitle are capped at three so years stay named.
_SEPARATOR = rf"\s*[.:){_DASH}]\s+(?=\S)"
_BARE_NUMBER_RE = re.compile(r"\d+")
_NUMBERED_TITLE_RE = re.compile(rf"(?P<number>\d{{1,3}}){_SEPARATOR}")
_SPELLED_TITLE_RE = re.compile(rf"(?P<number>{_SPELLED_NUMBER})(?:(?P<separator>{_SEPARATOR}).*)?", re.IGNORECASE)
# Sections that a leading track index ("01 - Prologue", "03 - Interlude") can
# precede; the section name identifies them, not the index.
_SECTION_RE = re.compile(
    r"(?:prologue|epilogue|interlude|introduction|foreword|preface|afterword|"
    r"acknowledge?ments|appendix|glossary|dedication|author'?s note|part|book)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NumberedTitle:
    """A chapter number read from a title, and what the title says after it.

    ``indexed`` marks a bare leading number before a subtitle ("02 - Title"):
    filenames use the same form for track order, so that number may be a track
    index rather than the chapter number.
    """

    number: int
    subtitle: str | None
    indexed: bool


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _spelled_number(text: str) -> int | None:
    tokens = [token for token in re.split(rf"[\s{_DASH}]+", text.casefold()) if token and token != "and"]
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
    return total if 0 < total <= _MAX_ROMAN_CHAPTER else None


def _chapter_label_number(match: re.Match[str]) -> int | None:
    if match.group("digits"):
        return int(match.group("digits"))
    if match.group("roman"):
        return _roman_number(match.group("roman"))
    return _spelled_number(match.group("words"))


def _subtitle(text: str) -> str | None:
    return _normalized(text) or None


def _after_index(value: str) -> str | None:
    """The subtitle after a bare leading number and separator, if the title has one."""
    if numbered := _NUMBERED_TITLE_RE.match(value):
        start = numbered.end()
    elif (spelled := _SPELLED_TITLE_RE.fullmatch(value)) and spelled.group("separator"):
        start = spelled.end("separator")
    else:
        return None
    return value[start:]


def _numbered_title(value: str) -> NumberedTitle | None:
    decorated = _DECORATED_NUMBER_RE.fullmatch(value)
    if decorated:
        return NumberedTitle(int(decorated.group(1) or decorated.group(2)), None, False)
    if (label := _CHAPTER_LABEL_RE.search(value)) and (number := _chapter_label_number(label)) is not None:
        after_label = label.end()
        return NumberedTitle(number, _subtitle(value[after_label:]), False)
    if _BARE_NUMBER_RE.fullmatch(value):
        return NumberedTitle(int(value), None, False)
    if (spelled := _SPELLED_TITLE_RE.fullmatch(value)) and not spelled.group("separator"):
        number = _spelled_number(value)
        return NumberedTitle(number, None, False) if number else None
    rest = _after_index(value)
    if rest is None or _SECTION_RE.match(rest):
        return None
    if numbered := _NUMBERED_TITLE_RE.match(value):
        return NumberedTitle(int(numbered.group("number")), _subtitle(rest), True)
    number = _spelled_number(spelled.group("number")) if spelled else None
    return NumberedTitle(number, _subtitle(rest), True) if number else None


@lru_cache(maxsize=4096)
def _parse(title: str | None) -> tuple[tuple[str, int | str] | None, NumberedTitle | None]:
    value = " ".join((title or "").split()).strip()
    if not value or _CREDITS_RE.search(value):
        return None, None
    # Only a complete numeric label or a chapter label counts; part titles,
    # dates and decorated numbers inside longer titles stay named.
    if (numbered := _numbered_title(value)) is not None:
        return ("chapter", numbered.number), numbered
    # "01 - Prologue" is the prologue, whatever its track index.
    if (rest := _after_index(value)) is not None and _SECTION_RE.match(rest):
        value = rest
    lowered = value.casefold()
    if "epilogue" in lowered:
        return ("named", "epilogue"), None
    if "prologue" in lowered:
        return ("named", "prologue"), None
    return ("named", _normalized(value)), None


def numbered_title(title: str | None) -> NumberedTitle | None:
    """The chapter number a title states, if it states one; credits never do."""
    return _parse(title)[1]


def chapter_identity(title: str | None) -> tuple[str, int | str] | None:
    """Identify a chapter label so EPUB chapters and audio tracks can be paired.

    Numbered labels compare by number whatever their spelling ("Chapter 12",
    "[ 12 ]", "12. Title", "Twelve", "Chapter XII"); anything else compares by
    its normalized text. Credits have no chapter.
    """
    return _parse(title)[0]


def _subtitles_agree(first: str, second: str) -> bool:
    return f" {first} " in f" {second} " or f" {second} " in f" {first} "


def same_chapter(first: str | None, second: str | None) -> bool:
    """Whether two titles name the same chapter.

    A leading number before a subtitle may be a track index, so when either
    title has that form and both have subtitles, the subtitles must agree too:
    with a prologue as track 01, "02 - The Door" is chapter 1, "The Door".
    """
    identity = chapter_identity(first)
    if identity is None or identity != chapter_identity(second):
        return False
    first_number, second_number = numbered_title(first), numbered_title(second)
    if first_number is None or second_number is None or not (first_number.indexed or second_number.indexed):
        return True
    if first_number.subtitle is None or second_number.subtitle is None:
        return True
    return _subtitles_agree(first_number.subtitle, second_number.subtitle)


def normalized_title(title: str | None) -> str:
    """Title text for an exact comparison, ignoring case, spacing and punctuation."""
    return _normalized(title or "")
