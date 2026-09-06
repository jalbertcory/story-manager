"""Quote-aware text helpers shared by diarization and speech generation."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol
from collections.abc import Sequence

_SPEAKABLE_RE = re.compile(r"[\w\d]", re.UNICODE)


class SentenceText(Protocol):
    @property
    def id(self) -> int: ...

    @property
    def original_text(self) -> str: ...


class AttributedSentence(SentenceText, Protocol):
    @property
    def character_id(self) -> int | None: ...


@dataclass(frozen=True)
class SpeechSegment:
    """A contiguous span spoken by either a character or the narrator."""

    text: str
    is_dialogue: bool
    starts_quote: bool = False
    ends_quote: bool = False

    @property
    def has_speech(self) -> bool:
        return bool(_SPEAKABLE_RE.search(self.text))


def split_speech_segments(
    text: str,
    quote_state: str | None = None,
) -> tuple[list[SpeechSegment], str | None]:
    """Split dialogue from attribution/action prose without losing punctuation.

    ``quote_state`` is ``"curly"`` or ``"straight"`` when a quotation began in
    an earlier sentence or paragraph. Some sentence tokenizers attach an opening
    curly quote to the preceding sentence; an unmatched closing quote therefore
    also implies that the current sentence began inside dialogue.
    """

    if quote_state is None:
        first_open = text.find("“")
        first_close = text.find("”")
        if first_close >= 0 and (first_open < 0 or first_close < first_open):
            quote_state = "curly"

    segments: list[SpeechSegment] = []
    buffer: list[str] = []
    buffer_dialogue = quote_state is not None
    buffer_starts_quote = False

    def flush(*, ends_quote: bool = False) -> None:
        nonlocal buffer, buffer_starts_quote
        value = "".join(buffer).strip()
        if value:
            segments.append(
                SpeechSegment(
                    text=value,
                    is_dialogue=buffer_dialogue,
                    starts_quote=buffer_starts_quote,
                    ends_quote=ends_quote,
                )
            )
        buffer = []
        buffer_starts_quote = False

    for character in text:
        if character == "“":
            if quote_state is None:
                flush()
                quote_state = "curly"
                buffer_dialogue = True
                buffer_starts_quote = True
            buffer.append(character)
            continue

        if character == "”" and quote_state == "curly":
            buffer.append(character)
            flush(ends_quote=True)
            quote_state = None
            buffer_dialogue = False
            continue

        if character == '"' and quote_state != "curly":
            if quote_state == "straight":
                buffer.append(character)
                flush(ends_quote=True)
                quote_state = None
                buffer_dialogue = False
            else:
                flush()
                quote_state = "straight"
                buffer_dialogue = True
                buffer_starts_quote = True
                buffer.append(character)
            continue

        buffer.append(character)

    flush()
    return segments, quote_state


def quote_groups(sentences: Sequence[SentenceText]) -> list[list[int]]:
    """Return sentence-id groups that belong to uninterrupted quotations."""

    groups: list[list[int]] = []
    current_group: list[int] | None = None
    quote_state: str | None = None

    for sentence in sentences:
        segments, quote_state = split_speech_segments(sentence.original_text, quote_state)
        for segment in segments:
            if not segment.is_dialogue:
                continue
            if segment.starts_quote or current_group is None:
                current_group = []
                groups.append(current_group)
            if segment.has_speech and sentence.id not in current_group:
                current_group.append(sentence.id)
            if segment.ends_quote:
                current_group = None

    return [group for group in groups if group]


def quote_group_ids(sentences: Sequence[SentenceText]) -> dict[int, int]:
    """Map unambiguous sentence ids to a stable chapter-local quote group."""

    memberships: dict[int, list[int]] = {}
    for group_id, sentence_ids in enumerate(quote_groups(sentences), start=1):
        for sentence_id in sentence_ids:
            memberships.setdefault(sentence_id, []).append(group_id)
    return {sentence_id: group_ids[0] for sentence_id, group_ids in memberships.items() if len(group_ids) == 1}
