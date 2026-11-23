"""Pronunciation lexicon: respell names and invented words before synthesis.

Rules live at three scopes. A book's rule wins over its series' rule, which
wins over a library-wide rule for the same term. Only the text sent to the
speech provider changes; the stored sentence text, highlighting and alignment
keep the author's spelling.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import re
from typing import Literal

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..lifecycle import SentenceStatus
from ..models import AudiobookChapter, AudiobookPronunciation, AudiobookSentence, Book

PronunciationScope = Literal["book", "series", "global"]
_SCOPE_PRIORITY: dict[PronunciationScope, int] = {"global": 0, "series": 1, "book": 2}
# Pipeline expression tags such as ``[laughter]`` are provider controls, not prose.
_TAG_PATTERN = r"\[[^\]\n]*\]"


@dataclass(frozen=True)
class PronunciationRule:
    term: str
    spoken: str
    case_sensitive: bool = False


def rule_scope(rule: AudiobookPronunciation) -> PronunciationScope:
    if rule.book_id is not None:
        return "book"
    if rule.series_name is not None:
        return "series"
    return "global"


def _term_key(term: str) -> str:
    return " ".join(term.split()).casefold()


def _term_pattern(term: str) -> str:
    """Match the term as whole words, tolerating any whitespace between its words."""
    body = r"\s+".join(re.escape(word) for word in term.split())
    return rf"(?<!\w){body}(?!\w)"


class Lexicon:
    """A compiled, single-pass set of respellings.

    All terms are matched in one scan, longest first, so one rule's output is
    never rewritten by another and "Kael'thas Sunstrider" wins over "Kael'thas".
    """

    def __init__(self, rules: Iterable[PronunciationRule] = ()) -> None:
        unique: dict[tuple[str, bool], PronunciationRule] = {}
        for rule in rules:
            if rule.term.strip() and rule.spoken.strip():
                unique.setdefault((_term_key(rule.term), rule.case_sensitive), rule)
        # Longest first; at equal length an exact-case rule beats a relaxed one.
        self._rules = sorted(unique.values(), key=lambda rule: (-len(_term_key(rule.term)), not rule.case_sensitive))
        self._pattern: re.Pattern[str] | None = None
        if self._rules:
            alternatives = [f"(?P<tag>{_TAG_PATTERN})"]
            for index, rule in enumerate(self._rules):
                flag = "" if rule.case_sensitive else "(?i:"
                close = "" if rule.case_sensitive else ")"
                alternatives.append(f"(?P<r{index}>{flag}{_term_pattern(rule.term)}{close})")
            self._pattern = re.compile("|".join(alternatives))

    def __bool__(self) -> bool:
        return bool(self._rules)

    @property
    def rules(self) -> Sequence[PronunciationRule]:
        return tuple(self._rules)

    def _rule_for(self, match: re.Match[str]) -> PronunciationRule | None:
        group = match.lastgroup
        if group is None or group == "tag":
            return None
        return self._rules[int(group[1:])]

    def apply(self, text: str) -> str:
        if self._pattern is None:
            return text

        def replace(match: re.Match[str]) -> str:
            rule = self._rule_for(match)
            return match.group(0) if rule is None else rule.spoken.strip()

        return self._pattern.sub(replace, text)

    def changes(self, text: str) -> bool:
        if self._pattern is None:
            return False
        return any(self._rule_for(match) is not None for match in self._pattern.finditer(text))


EMPTY_LEXICON = Lexicon()


def effective_rules(rules: Iterable[AudiobookPronunciation]) -> list[AudiobookPronunciation]:
    """Keep the most specific rule for each term."""
    chosen: dict[str, AudiobookPronunciation] = {}
    for rule in rules:
        key = _term_key(rule.term)
        current = chosen.get(key)
        if current is None or _SCOPE_PRIORITY[rule_scope(rule)] > _SCOPE_PRIORITY[rule_scope(current)]:
            chosen[key] = rule
    return list(chosen.values())


def build_lexicon(rules: Iterable[AudiobookPronunciation]) -> Lexicon:
    return Lexicon(
        PronunciationRule(term=rule.term, spoken=rule.spoken, case_sensitive=rule.case_sensitive)
        for rule in effective_rules(rules)
    )


async def rules_for_book(db: AsyncSession, book: Book) -> list[AudiobookPronunciation]:
    """Every rule that can apply to this book, including overridden ones."""
    scopes = [
        AudiobookPronunciation.book_id == book.id,
        (AudiobookPronunciation.book_id.is_(None) & AudiobookPronunciation.series_name.is_(None)),
    ]
    if book.series:
        scopes.append(
            AudiobookPronunciation.book_id.is_(None) & (func.lower(AudiobookPronunciation.series_name) == book.series.lower())
        )
    result = await db.execute(
        select(AudiobookPronunciation).where(or_(*scopes)).order_by(func.lower(AudiobookPronunciation.term))
    )
    return list(result.scalars().all())


async def load_book_lexicon(db: AsyncSession, book_id: int) -> Lexicon:
    book = await db.get(Book, book_id)
    if book is None:
        return EMPTY_LEXICON
    return build_lexicon(await rules_for_book(db, book))


async def find_scope_duplicate(
    db: AsyncSession,
    *,
    term: str,
    book_id: int | None,
    series_name: str | None,
    exclude_id: int | None = None,
) -> AudiobookPronunciation | None:
    query = select(AudiobookPronunciation)
    if book_id is not None:
        query = query.where(AudiobookPronunciation.book_id == book_id)
    elif series_name is not None:
        query = query.where(
            AudiobookPronunciation.book_id.is_(None),
            func.lower(AudiobookPronunciation.series_name) == series_name.lower(),
        )
    else:
        query = query.where(AudiobookPronunciation.book_id.is_(None), AudiobookPronunciation.series_name.is_(None))
    result = await db.execute(query)
    key = _term_key(term)
    for rule in result.scalars().all():
        if rule.id != exclude_id and _term_key(rule.term) == key:
            return rule
    return None


async def books_in_rule_scope(db: AsyncSession, rule: AudiobookPronunciation) -> list[int]:
    """IDs of the narrated books a rule can reach."""
    query = select(Book.id).where(Book.deleted_at.is_(None), Book.id.in_(select(AudiobookChapter.book_id).distinct()))
    if rule.book_id is not None:
        query = query.where(Book.id == rule.book_id)
    elif rule.series_name is not None:
        query = query.where(func.lower(Book.series) == rule.series_name.lower())
    result = await db.execute(query.order_by(Book.id))
    return [row[0] for row in result.all()]


def _like_fragment(term: str) -> str:
    """The first word of a term, escaped for a LIKE prefilter."""
    words = term.split()
    fragment = words[0] if words else ""
    return fragment.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _matching_sentences(
    db: AsyncSession,
    book_id: int,
    terms: Sequence[PronunciationRule],
    *,
    generated_only: bool,
) -> list[AudiobookSentence]:
    lexicon = Lexicon(terms)
    if not lexicon:
        return []
    text_filters = []
    for rule in lexicon.rules:
        fragment = f"%{_like_fragment(rule.term)}%"
        text_filters.append(AudiobookSentence.original_text.ilike(fragment, escape="\\"))
        text_filters.append(AudiobookSentence.tagged_text.ilike(fragment, escape="\\"))
    query = (
        select(AudiobookSentence)
        .join(AudiobookChapter, AudiobookChapter.id == AudiobookSentence.chapter_id)
        .where(AudiobookChapter.book_id == book_id, or_(*text_filters))
    )
    if generated_only:
        query = query.where(AudiobookSentence.status == SentenceStatus.AUDIO_GENERATED.value)
    result = await db.execute(query)
    return [sentence for sentence in result.scalars().all() if lexicon.changes(sentence.tagged_text or sentence.original_text)]


async def count_term_sentences(db: AsyncSession, book_id: int, rule: PronunciationRule) -> int:
    return len(await _matching_sentences(db, book_id, [rule], generated_only=False))


async def regenerate_sentences_with_terms(
    db: AsyncSession,
    book_ids: Sequence[int],
    terms: Sequence[PronunciationRule],
) -> int:
    """Send already-narrated sentences containing any term back for speech."""
    from ..crud.audiobook import invalidate_packaged_audiobook

    # Matching is on the written term only; the respelling is irrelevant here.
    reset_total = 0
    for book_id in book_ids:
        sentences = await _matching_sentences(db, book_id, terms, generated_only=True)
        if not sentences:
            continue
        sentence_ids = [sentence.id for sentence in sentences]
        chapter_ids = sorted({sentence.chapter_id for sentence in sentences})
        await db.execute(
            update(AudiobookSentence)
            .where(AudiobookSentence.id.in_(sentence_ids))
            .values(
                status=SentenceStatus.READY_FOR_AUDIO.value,
                audio_file_path=None,
                audio_duration_ms=None,
                generation_group_id=None,
                voice_similarity=None,
                tts_attempts=None,
            )
        )
        await db.execute(
            update(AudiobookChapter)
            .where(AudiobookChapter.id.in_(chapter_ids))
            .values(needs_reassembly=True, preview_status=None, preview_error=None)
        )
        await db.commit()
        await invalidate_packaged_audiobook(db, book_id)
        reset_total += len(sentence_ids)
    return reset_total
