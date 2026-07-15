"""Phases 2 & 3: LLM-based character roster generation and sentence diarization."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..models import AudiobookSettings, Book

logger = logging.getLogger(__name__)

STUB_PROVIDER = "stub"

DEFAULT_ROSTER_PROMPT = """\
You are a literary analyst preparing a cast list for an audiobook. Analyze the sampled excerpts from across the \
book and identify the primary narrator plus the major or recurring speaking characters. Merge aliases, titles, and \
surname-only references into one character. Do not include authors, publishers, places, organizations, unnamed \
crowds, or one-line background figures. Prefer people with repeated mentions across the book and omit one-scene \
figures even if they appear in an excerpt. Return no more than 18 characters.

For each character produce:
- name: canonical full name; use "Narrator" for the narrative prose voice
- aliases: other names, surnames, nicknames, ranks, or titles used for this person
- description: a concise description of their personality, relationships, and role
- evidence: 1-3 short exact quotations from the supplied text supporting the identification
- voice_design_prompt: an OmniVoice voice parameter string using ONLY these tokens:
  [gender-{{male|female|neutral}}] [pitch-{{low|medium|high}}] [speed-{{slow|normal|fast}}]
  Optional: [accent-{{british|american|australian}}] [age-{{young|middle|old}}]
  Example: [gender-male][pitch-low][speed-normal][age-middle]
  Always include gender, pitch, speed, and age. Use the textual evidence to make recurring characters distinct;
  do not give every character the same generic profile. Add an accent only when the text supports it.
- is_narrator: true only for an entry named exactly "Narrator". In first-person books, the protagonist must be a \
  separate character with is_narrator false so their spoken dialogue has a distinct voice.

Also produce a spoiler-light 2-4 sentence book_summary grounded only in these excerpts.
Return JSON with keys book_summary and characters. No markdown or explanation.

Candidate name frequency hints from the complete book (not ground truth; ignore non-people):
{candidate_hints}

Existing shared roster for this series (reuse these canonical identities and voice profiles when they appear):
{series_roster}

Names with explicit dialogue-tag hits (for example, "Harry said") are confirmed speaking candidates. Include the
highest-hit confirmed speakers unless the evidence clearly shows they are not a person. Do not substitute low-count
cameos for them. If the story is first-person, also include the named protagonist separately from Narrator.

Sampled excerpts:
{text}
"""

DEFAULT_DIARIZATION_PROMPT = """\
You are a script editor. Assign each sentence to a speaker from the character roster and add non-verbal \
expression tags where appropriate.

Assign quoted dialogue to the person speaking it, even when the attribution (for example, "she asked") is in an
adjacent sentence. Keep attribution and action prose on Narrator. If an unnamed or one-scene speaker is absent from
the recurring roster, use "Minor Female Voice" or "Minor Male Voice" when present instead of Narrator.

Character roster (JSON):
{roster_json}

Chapter summary so far:
{chapter_summary}

Previous context (last 8 sentences):
{context}

Sentences to process (JSON array with id and text):
{sentences_json}

For each sentence return:
- id: the sentence id (integer)
- character_id: the character id from the roster (use the narrator's id for narration; null if uncertain)
- tagged_text: the sentence text with optional non-verbal tags like [laughter], [sigh], [whisper], [shout], or null
  when no tag is needed (do not repeat unchanged text)
- confidence: a number from 0 to 1 for the speaker assignment
- reason: a brief evidence-based reason, such as an adjacent dialogue tag or turn-taking context
  (12 words or fewer)

Also return chapter_summary: an updated spoiler-light summary incorporating this batch and the prior summary, using
no more than 100 words.
The roster descriptions are identity hints only and may be inaccurate. Ground the chapter summary exclusively in the
sentence text and prior chapter summary; never import plot events, body changes, relationships, or backstory from a
character description.
Return JSON with keys assignments and chapter_summary. No markdown or explanation.
"""

_ALLOWED_EXPRESSION_TAGS = {"laughter", "sigh", "whisper", "shout"}
_BRACKET_TAG_RE = re.compile(r"\[([^\[\]]+)\]")
_GENDERED_ATTRIBUTION_RE = re.compile(
    r"\b(she|he)\s+(?:said|asked|replied|yelled|shouted|whispered|muttered|added|continued|answered|snapped|"
    r"repeated|remarked|responded|interrupted)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_ATTRIBUTION_RE = re.compile(
    r"\bI\s+(?:said|asked|replied|yelled|shouted|whispered|muttered|added|continued|answered|snapped|reminded)\b",
    re.IGNORECASE,
)
_DIALOGUE_ATTRIBUTION_IN_SENTENCE_RE = re.compile(
    r"\b(?:said|asked|replied|yelled|shouted|whispered|muttered|added|continued|answered|snapped)\b" r"[^“\"]{0,80}[“\"]",
    re.IGNORECASE,
)
MAX_DIARIZATION_BATCH_SIZE = 10
MIN_DIARIZATION_BATCH_SIZE = 5
MIN_STORY_CHAPTER_SENTENCES = 40

ROSTER_SCHEMA = {
    "type": "object",
    "properties": {
        "book_summary": {"type": "string"},
        "characters": {
            "type": "array",
            "maxItems": 18,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "aliases": {
                        "type": "array",
                        "maxItems": 10,
                        "items": {"type": "string"},
                    },
                    "description": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {"type": "string"},
                    },
                    "voice_design_prompt": {"type": "string"},
                    "is_narrator": {"type": "boolean"},
                },
                "required": [
                    "name",
                    "aliases",
                    "description",
                    "evidence",
                    "voice_design_prompt",
                    "is_narrator",
                ],
            },
        },
    },
    "required": ["book_summary", "characters"],
}

DIARIZATION_SCHEMA = {
    "type": "object",
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "character_id": {"type": ["integer", "null"]},
                    "tagged_text": {"type": ["string", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string", "maxLength": 160},
                },
                "required": ["id", "character_id", "tagged_text", "confidence", "reason"],
            },
        },
        "chapter_summary": {"type": "string", "maxLength": 1200},
    },
    "required": ["assignments", "chapter_summary"],
}


async def _call_llm(
    settings: AudiobookSettings,
    messages: list[dict[str, Any]],
    *,
    response_schema: dict[str, Any] | None = None,
) -> str:
    """Route to the configured LLM provider and return the text response."""
    provider = (settings.llm_provider or "openai").lower()
    if provider != "ollama" and not settings.llm_api_key and not settings.llm_base_url:
        raise RuntimeError("LLM not configured: set llm_api_key or llm_base_url in Audio Settings.")

    model = settings.llm_model or ("qwen3.5:9b" if provider == "ollama" else "gpt-4o")

    headers = {"Content-Type": "application/json"}

    if provider == "ollama":
        url = (settings.llm_base_url or "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": response_schema or "json",
            "options": {"temperature": 0, "num_ctx": 32768, "num_predict": 8192},
            "keep_alive": "30m",
        }
        timeout = httpx.Timeout(600.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.is_error:
                raise RuntimeError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:1000]}")
            data = resp.json()
        return data["message"]["content"]

    if provider == "anthropic":
        url = (settings.llm_base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        headers["x-api-key"] = settings.llm_api_key or ""
        headers["anthropic-version"] = "2023-06-01"
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "messages": messages,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return data["content"][0]["text"]

    else:
        # OpenAI-compatible (openai, custom, local)
        base = settings.llm_base_url or "https://api.openai.com"
        url = base.rstrip("/") + "/v1/chat/completions"
        if settings.llm_api_key:
            headers["Authorization"] = f"Bearer {settings.llm_api_key}"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
        }
        if response_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "audiobook_analysis", "strict": True, "schema": response_schema},
            }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first and last fence lines
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return text


def _remove_trailing_json_commas(text: str) -> str:
    """Remove commas immediately before ] or } without changing JSON strings."""
    output: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            output.append(char)
            continue
        if char in "]}":
            previous = len(output) - 1
            while previous >= 0 and output[previous].isspace():
                previous -= 1
            if previous >= 0 and output[previous] == ",":
                del output[previous]
        output.append(char)
    return "".join(output)


def _extract_json(raw: str) -> Any:
    """Parse structured output and repair common local-model trailing commas."""
    text = _strip_json_fence(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError as original_error:
        repaired = _remove_trailing_json_commas(text)
        if repaired == text:
            raise
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            raise original_error


def _normalise_diarization_result(batch_result: Any, expected_ids: set[int]) -> dict[str, Any]:
    """Require exactly one assignment for every requested sentence."""
    if isinstance(batch_result, list):
        batch_result = {"assignments": batch_result, "chapter_summary": None}
    if not isinstance(batch_result, dict) or not isinstance(batch_result.get("assignments"), list):
        raise ValueError(f"Expected a JSON object with assignments, got {type(batch_result).__name__}")

    result_ids = [
        result.get("id")
        for result in batch_result["assignments"]
        if isinstance(result, dict) and isinstance(result.get("id"), int)
    ]
    result_id_set = set(result_ids)
    missing = sorted(expected_ids - result_id_set)
    unexpected = sorted(result_id_set - expected_ids)
    duplicates = sorted(
        sentence_id for sentence_id, count in Counter(result_ids).items() if sentence_id in expected_ids and count > 1
    )
    if missing or duplicates or len(result_ids) != len(batch_result["assignments"]):
        raise ValueError(
            "Invalid assignment coverage: "
            f"missing={missing[:10]}, unexpected={unexpected[:10]}, duplicates={duplicates[:10]}"
        )
    if unexpected:
        logger.warning("Ignoring %d unsolicited diarization assignments: %s", len(unexpected), unexpected[:10])
        batch_result["assignments"] = [result for result in batch_result["assignments"] if result.get("id") in expected_ids]
    return batch_result


def _sanitize_tagged_text(original: str, tagged: Any) -> str:
    """Accept expression-tag insertion, but reject unsupported tags or prose rewrites."""
    if not isinstance(tagged, str) or not tagged.strip():
        return original

    def remove_unknown(match: re.Match[str]) -> str:
        token = match.group(1).strip().casefold()
        if token in _ALLOWED_EXPRESSION_TAGS or match.group(0) in original:
            return match.group(0)
        return ""

    cleaned = _BRACKET_TAG_RE.sub(remove_unknown, tagged).strip()
    without_allowed = _BRACKET_TAG_RE.sub(
        lambda match: "" if match.group(1).strip().casefold() in _ALLOWED_EXPRESSION_TAGS else match.group(0),
        cleaned,
    )
    if " ".join(without_allowed.split()) != " ".join(original.split()):
        return original
    return cleaned


def _apply_speaker_guardrails(
    *,
    text: str,
    next_text: str,
    character_id: int | None,
    narrator_id: int | None,
    protagonist_id: int | None,
    minor_female_id: int | None,
    minor_male_id: int | None,
    reason: str,
) -> tuple[int | None, str, float | None]:
    """Correct two common local-model ID errors without inventing named speakers."""
    starts_with_quote = text.lstrip().startswith(("“", '"'))
    has_quote = any(quote in text for quote in ("“", "”", '"'))
    has_dialogue = starts_with_quote or bool(_DIALOGUE_ATTRIBUTION_IN_SENTENCE_RE.search(text))

    current_first_person = _FIRST_PERSON_ATTRIBUTION_RE.search(text)
    next_first_person = starts_with_quote and _FIRST_PERSON_ATTRIBUTION_RE.match(next_text.lstrip())
    if protagonist_id is not None and has_quote and (current_first_person or next_first_person):
        return protagonist_id, "Deterministic first-person dialogue attribution", 0.99

    current_gender = _GENDERED_ATTRIBUTION_RE.search(text)
    next_gender = starts_with_quote and _GENDERED_ATTRIBUTION_RE.match(next_text.lstrip())
    attribution = current_gender or next_gender
    if has_quote and attribution:
        gender = attribution.group(1).casefold()
        fallback_id = minor_female_id if gender == "she" else minor_male_id
        if fallback_id is not None:
            return fallback_id, f"Deterministic {gender} dialogue attribution to minor voice", 0.98

    if character_id == narrator_id and starts_with_quote and protagonist_id is not None:
        return protagonist_id, "Deterministic first-person dialogue fallback", 0.75

    if character_id != narrator_id and not has_dialogue:
        return narrator_id, "Deterministic prose/narration guardrail", 0.98

    return character_id, reason, None


def _advance_open_dialogue_speaker(
    text: str,
    resolved_character_id: int | None,
    *,
    narrator_id: int | None,
    minor_female_id: int | None,
    minor_male_id: int | None,
    current_open_speaker_id: int | None,
) -> int | None:
    """Track a curly-quoted utterance split across sentence records."""
    opens = text.count("“")
    closes = text.count("”")
    if opens > closes:
        prefix = text.rsplit("“", 1)[0]
        pronouns = re.findall(r"\b(she|her|he|him)\b", prefix[-120:], re.IGNORECASE)
        if pronouns:
            gender = pronouns[-1].casefold()
            return minor_female_id if gender in {"she", "her"} else minor_male_id
        if resolved_character_id != narrator_id:
            return resolved_character_id
        return None
    if closes > opens:
        return None
    return current_open_speaker_id


async def _build_roster_excerpt(chapters, db: AsyncSession) -> str:
    """Sample real story chapters across the book instead of front matter."""
    candidates: list[tuple[Any, list[Any]]] = []
    for chapter in chapters:
        sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        if _starts_back_matter(sentences):
            break
        if len(sentences) >= 40:
            candidates.append((chapter, sentences))

    if not candidates:
        for chapter in chapters:
            sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
            if _starts_back_matter(sentences):
                break
            if sentences:
                candidates.append((chapter, sentences))

    if len(candidates) > 8:
        indexes = sorted({round(index * (len(candidates) - 1) / 7) for index in range(8)})
        selected = [candidates[index] for index in indexes]
    else:
        selected = candidates

    excerpts: list[str] = []
    for chapter, sentences in selected:
        chapter_text = " ".join(sentence.original_text for sentence in sentences)
        excerpts.append(f"### Chapter {chapter.chapter_number}\n{chapter_text[:4000]}")
    return "\n\n".join(excerpts)[:32000]


_CANDIDATE_TOKEN_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")
_FULL_NAME_RE = re.compile(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b")
_DIALOGUE_TAG_RE = re.compile(
    r"\b([A-Z][a-z]{2,})\s+(?:said|asked|replied|yelled|shouted|whispered|added|continued|noted|answered|"
    r"snapped|muttered|called|agreed|insisted)\b|\b(?:said|asked|replied|yelled|shouted|whispered|added|"
    r"continued|noted|answered|snapped|muttered|called|agreed|insisted)\s+([A-Z][a-z]{2,})\b"
)
_CANDIDATE_STOP_WORDS = {
    "About",
    "After",
    "Again",
    "And",
    "Are",
    "Before",
    "But",
    "Chapter",
    "Copyright",
    "Could",
    "Did",
    "Does",
    "Earth",
    "For",
    "From",
    "Had",
    "Has",
    "Have",
    "Here",
    "How",
    "However",
    "Into",
    "Just",
    "Like",
    "Maybe",
    "More",
    "Much",
    "Neither",
    "Never",
    "Next",
    "None",
    "Nothing",
    "Now",
    "One",
    "Only",
    "Other",
    "Our",
    "Part",
    "Right",
    "She",
    "Since",
    "Some",
    "Something",
    "Still",
    "That",
    "The",
    "Then",
    "There",
    "These",
    "They",
    "This",
    "Those",
    "Through",
    "Very",
    "Was",
    "We",
    "Well",
    "What",
    "When",
    "Where",
    "Which",
    "While",
    "Who",
    "Why",
    "With",
    "Would",
    "Yes",
    "You",
    "Your",
}
_NAME_TITLE_WORDS = {
    "Administrator",
    "Admiral",
    "Captain",
    "Colonel",
    "Corporal",
    "Doctor",
    "Doubtful",
    "General",
    "Lieutenant",
    "Major",
    "Master",
    "Mister",
    "Private",
    "Professor",
    "Sergeant",
}
_BACK_MATTER_HEADINGS = (
    "ACKNOWLEDGMENTS",
    "ACKNOWLEDGEMENTS",
    "ABOUT THE AUTHOR",
    "ALSO BY ",
    "EXCERPT FROM",
    "THIS IS A WORK OF FICTION",
    "TOR BOOKS BY ",
)
_FIRST_PERSON_GENDER_RE = re.compile(
    r"\bI(?:'m| am| was)\s+(?:an?\s+)?(?:old\s+|young\s+)?(man|male|widower|woman|female|widow)\b",
    re.IGNORECASE,
)


def _starts_back_matter(sentences: list[Any]) -> bool:
    if not sentences:
        return False
    heading = " ".join(str(sentences[0].original_text).split()).upper()
    return any(heading.startswith(marker) for marker in _BACK_MATTER_HEADINGS)


async def _infer_first_person_gender(chapters, db: AsyncSession) -> str | None:
    counts: Counter[str] = Counter()
    for chapter in chapters:
        sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        if _starts_back_matter(sentences):
            break
        for sentence in sentences:
            for match in _FIRST_PERSON_GENDER_RE.finditer(sentence.original_text):
                token = match.group(1).casefold()
                counts["male" if token in {"man", "male", "widower"} else "female"] += 1
    if counts["male"] >= 1 and counts["male"] >= counts["female"] * 2:
        return "male"
    if counts["female"] >= 1 and counts["female"] >= counts["male"] * 2:
        return "female"
    return None


def _infer_candidate_gender(texts: list[str], names: set[str]) -> str | None:
    """Infer gender only when repeated, local pronoun evidence is decisive."""
    pronouns: Counter[str] = Counter()
    patterns = [re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE) for name in names if name]
    self_intro_patterns = [
        re.compile(
            rf"^\s*[“\"]?{re.escape(name)}\s*[,.”\"]+\s*(she|he)\s+" r"(?:said|replied|answered)\b",
            re.IGNORECASE,
        )
        for name in names
        if " " in name
    ]
    for text in texts:
        for pattern in self_intro_patterns:
            match = pattern.search(text)
            if match:
                return "female" if match.group(1).casefold() == "she" else "male"
        if not any(pattern.search(text) for pattern in patterns):
            continue
        pronouns.update(token.casefold() for token in re.findall(r"\b(?:he|him|his|she|her|hers)\b", text, re.I))
    male = sum(pronouns[token] for token in ("he", "him", "his"))
    female = sum(pronouns[token] for token in ("she", "her", "hers"))
    if male >= 3 and male >= female * 2:
        return "male"
    if female >= 3 and female >= male * 2:
        return "female"
    return None


def _normalise_voice_prompt(value: Any, *, gender: str | None = None) -> str:
    """Keep OmniVoice parameters valid and apply evidence-backed gender."""
    text = str(value or "")

    def token(kind: str, allowed: set[str], default: str) -> str:
        match = re.search(rf"\[{kind}-([^\]]+)\]", text, re.IGNORECASE)
        candidate = match.group(1).casefold() if match else default
        return candidate if candidate in allowed else default

    selected_gender = gender or token("gender", {"male", "female", "neutral"}, "neutral")
    parts = [
        f"[gender-{selected_gender}]",
        f"[pitch-{token('pitch', {'low', 'medium', 'high'}, 'medium')}]",
        f"[speed-{token('speed', {'slow', 'normal', 'fast'}, 'normal')}]",
    ]
    accent = token("accent", {"british", "american", "australian"}, "")
    if accent:
        parts.append(f"[accent-{accent}]")
    parts.append(f"[age-{token('age', {'young', 'middle', 'old'}, 'middle')}]")
    return "".join(parts)


async def _build_character_candidate_analysis(chapters, db: AsyncSession) -> tuple[str, list[dict[str, Any]]]:
    """Provide whole-book evidence so sampled cameos do not crowd out recurring cast."""
    counts: Counter[str] = Counter()
    contextual_counts: Counter[str] = Counter()
    dialogue_counts: Counter[str] = Counter()
    dialogue_examples: dict[str, str] = {}
    full_name_counts: Counter[str] = Counter()
    all_texts: list[str] = []
    for chapter in chapters:
        chapter_sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        if _starts_back_matter(chapter_sentences):
            break
        for sentence in chapter_sentences:
            text = sentence.original_text
            all_texts.append(text)
            for match in _CANDIDATE_TOKEN_RE.finditer(text):
                token = match.group(0)
                if token in _CANDIDATE_STOP_WORDS:
                    continue
                counts[token] += 1
                if match.start() > 0:
                    contextual_counts[token] += 1
            for match in _FULL_NAME_RE.finditer(text):
                first, last = match.groups()
                if first not in _CANDIDATE_STOP_WORDS and last not in _CANDIDATE_STOP_WORDS and first not in _NAME_TITLE_WORDS:
                    full_name_counts[f"{first} {last}"] += 1
            for match in _DIALOGUE_TAG_RE.finditer(text):
                name = match.group(1) or match.group(2)
                if name in _CANDIDATE_STOP_WORDS:
                    continue
                dialogue_counts[name] += 1
                dialogue_examples.setdefault(name, text[:220])

    candidates = [
        (name, count, contextual_counts[name], dialogue_counts[name])
        for name, count in counts.items()
        if contextual_counts[name] >= 2 or count >= 8
    ]
    candidates.sort(key=lambda item: (item[3], item[2], item[1], item[0]), reverse=True)
    lines = []
    for name, count, _, dialogue_count in candidates[:50]:
        line = f"- {name}: {count} mentions; {dialogue_count} explicit dialogue tags"
        if dialogue_count and name in dialogue_examples:
            line += f'; example: "{dialogue_examples[name]}"'
        lines.append(line)
    confirmed = []
    for name, count, _, dialogue_count in candidates:
        if dialogue_count < 5:
            continue
        surname_matches = [
            (full_name, full_count) for full_name, full_count in full_name_counts.items() if full_name.split()[-1] == name
        ]
        first_name_matches = [
            (full_name, full_count) for full_name, full_count in full_name_counts.items() if full_name.split()[0] == name
        ]
        matches = surname_matches or first_name_matches
        canonical_name = max(matches, key=lambda item: (item[1], item[0]))[0] if matches else name
        identity_names = {canonical_name} if " " in canonical_name else {name}
        confirmed.append(
            {
                "name": name,
                "canonical_name": canonical_name,
                "mention_count": count,
                "dialogue_count": dialogue_count,
                "evidence": dialogue_examples.get(name),
                "gender": _infer_candidate_gender(all_texts, identity_names),
                "required": True,
            }
        )

    # Full names are useful for validating an LLM-produced protagonist even
    # when a first-person book rarely uses their name in dialogue tags. They
    # are identity metadata only and are not promoted into the roster by
    # themselves.
    known_canonical_names = {candidate["canonical_name"].casefold() for candidate in confirmed}
    for full_name, full_count in full_name_counts.most_common():
        if full_count < 3 or full_name.casefold() in known_canonical_names:
            continue
        first, last = full_name.split()
        if max(counts[first], counts[last]) < 8:
            continue
        confirmed.append(
            {
                "name": full_name,
                "canonical_name": full_name,
                "mention_count": full_count,
                "dialogue_count": 0,
                "evidence": next(
                    (text[:220] for text in all_texts if re.search(rf"\b{re.escape(full_name)}\b", text)),
                    None,
                ),
                "gender": _infer_candidate_gender(all_texts, {full_name}),
                "required": False,
            }
        )
        known_canonical_names.add(full_name.casefold())

    required = [candidate for candidate in confirmed if candidate["required"]]
    required_names = ", ".join(dict.fromkeys(candidate["canonical_name"] for candidate in required[:16]))
    heading = f"REQUIRED confirmed speakers (include all): {required_names}\n" if required_names else ""
    return heading + ("\n".join(lines) or "(none)"), confirmed


async def _build_character_candidate_hints(chapters, db: AsyncSession) -> str:
    hints, _ = await _build_character_candidate_analysis(chapters, db)
    return hints


def _canonicalize_roster_characters(
    characters: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    grounding_corpus: str,
) -> list[dict[str, Any]]:
    """Merge split identities and replace speculative biographies with facts."""
    stats_by_canonical: dict[str, dict[str, Any]] = {}
    identity_lookup: dict[str, str] = {}
    for candidate in candidates:
        canonical_name = str(candidate.get("canonical_name") or candidate["name"]).strip()
        canonical_key = canonical_name.casefold()
        stats = stats_by_canonical.setdefault(
            canonical_key,
            {
                "canonical_name": canonical_name,
                "names": set(),
                "mention_count": 0,
                "dialogue_count": 0,
                "gender": None,
                "gender_score": -1,
                "required": False,
            },
        )
        original_name = str(candidate["name"]).strip()
        stats["names"].update({original_name, canonical_name})
        stats["mention_count"] = max(stats["mention_count"], int(candidate.get("mention_count") or 0))
        stats["dialogue_count"] = max(stats["dialogue_count"], int(candidate.get("dialogue_count") or 0))
        stats["required"] = stats["required"] or bool(candidate.get("required", True))
        gender = candidate.get("gender")
        gender_score = int(candidate.get("dialogue_count") or 0) + int(candidate.get("mention_count") or 0)
        if gender and gender_score > stats["gender_score"]:
            stats["gender"] = gender
            stats["gender_score"] = gender_score
        identity_lookup[original_name.casefold()] = canonical_key
        identity_lookup[canonical_key] = canonical_key

    merged: dict[str, dict[str, Any]] = {}
    for character in characters:
        character = dict(character)
        original_name = str(character["name"]).strip()
        lookup_keys = [original_name.casefold(), *(str(alias).strip().casefold() for alias in character["aliases"])]
        canonical_key = next((identity_lookup[key] for key in lookup_keys if key in identity_lookup), None)
        stats = stats_by_canonical.get(canonical_key or "")
        allowed_identity_names: set[str] = set()
        if stats and not character["is_narrator"]:
            character["name"] = stats["canonical_name"]
            allowed_identity_names = {name.casefold() for name in stats["names"]}
            character["aliases"] = [
                *character["aliases"],
                *(name for name in sorted(stats["names"]) if name.casefold() != character["name"].casefold()),
            ]
            if original_name.casefold() != character["name"].casefold():
                character["aliases"] = [*character["aliases"], original_name]
            dialogue_count = stats["dialogue_count"]
            mention_count = stats["mention_count"]
            if dialogue_count:
                character["description"] = (
                    f"Recurring speaking character identified from {dialogue_count} explicit dialogue "
                    f"attributions and {mention_count} name mentions."
                )
            else:
                character["description"] = f"Character identity grounded by {mention_count} full-name mentions."
            evidence_gender = stats["gender"] or ("neutral" if stats["required"] else None)
            character["voice_design_prompt"] = _normalise_voice_prompt(
                character.get("voice_design_prompt"), gender=evidence_gender
            )
        elif not character["is_narrator"]:
            character["description"] = "Speaking character identified from supplied story excerpts."
            character["voice_design_prompt"] = _normalise_voice_prompt(character.get("voice_design_prompt"))

        grounded_aliases = []
        for alias in character["aliases"]:
            value = " ".join(str(alias).split()).strip()
            if not value or value.casefold() == character["name"].casefold():
                continue
            if value.casefold() in allowed_identity_names or value.casefold() in grounding_corpus:
                grounded_aliases.append(value)
        character["aliases"] = list(dict.fromkeys(grounded_aliases))[:10]

        merge_key = character["name"].strip().casefold()
        existing = merged.get(merge_key)
        if existing is None:
            merged[merge_key] = character
            continue
        existing["aliases"] = list(dict.fromkeys([*existing["aliases"], *character["aliases"]]))[:10]
        existing["evidence"] = list(dict.fromkeys([*existing["evidence"], *character["evidence"]]))[:3]

    return list(merged.values())


async def generate_character_roster(
    book_id: int,
    db: AsyncSession,
    *,
    refresh_series_metadata: bool = False,
) -> None:
    """Phase 2: extract characters from book text and persist to audiobook_characters."""
    settings = await crud.audiobook.get_audiobook_settings(db)
    provider = (settings.llm_provider or STUB_PROVIDER).lower() if settings else STUB_PROVIDER

    book = await db.get(Book, book_id)
    if book is None:
        raise RuntimeError(f"Book {book_id} was deleted during roster generation.")

    chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    if not chapters:
        raise RuntimeError(f"No narratable chapters found for book {book_id} during roster generation.")

    context_chapters = list(chapters)
    series_profiles = []
    series_book_count = 1
    if book.series:
        series_profiles = await crud.audiobook.get_series_characters(db, book.series)
        sibling_books = await crud.get_books_by_series(db, book.series, skip=0, limit=1000)
        series_book_count = len(sibling_books)
        for sibling in sibling_books:
            if sibling.id == book_id:
                continue
            context_chapters.extend(await crud.audiobook.get_chapters_for_book(db, sibling.id))

    combined_text = await _build_roster_excerpt(context_chapters, db)
    candidate_hints, confirmed_speakers = await _build_character_candidate_analysis(context_chapters, db)
    first_person_gender = await _infer_first_person_gender(context_chapters, db)
    prompt_series_profiles = series_profiles
    if refresh_series_metadata and book.series:
        prompt_series_profiles = await crud.audiobook.get_sibling_series_characters(db, book.series, book_id)
    series_roster = (
        json.dumps(
            [
                {
                    "name": profile.name,
                    "aliases": profile.aliases or [],
                    "description": profile.description,
                    "voice_design_prompt": profile.voice_design_prompt,
                }
                for profile in prompt_series_profiles
            ],
            ensure_ascii=False,
        )
        if prompt_series_profiles
        else "(none yet)"
    )
    await crud.audiobook.update_book_pipeline_progress(
        db,
        book_id,
        current=0,
        total=1,
        detail=(
            f"Analyzing recurring characters across {series_book_count} series books"
            if book.series and series_book_count > 1
            else "Analyzing story excerpts for recurring characters"
        ),
    )

    if provider == STUB_PROVIDER:
        roster_result = {
            "book_summary": "Deterministic local harness analysis.",
            "characters": [
                {
                    "name": "Narrator",
                    "aliases": [],
                    "description": "Deterministic local harness narrator.",
                    "evidence": [],
                    "voice_design_prompt": "[gender-neutral][pitch-medium][speed-normal]",
                    "is_narrator": True,
                }
            ],
        }
    else:
        prompt_template = settings.roster_prompt_template or DEFAULT_ROSTER_PROMPT
        prompt = prompt_template.format(
            text=combined_text,
            candidate_hints=candidate_hints,
            series_roster=series_roster,
        )
        logger.info("Calling LLM for character roster (book %s).", book_id)
        await crud.audiobook.update_book_pipeline_progress(
            db,
            book_id,
            current=0,
            total=1,
            detail=f"Waiting for {settings.llm_model or provider} roster analysis",
            llm_request_increment=1,
        )
        raw = await _call_llm(
            settings,
            [{"role": "user", "content": prompt}],
            response_schema=ROSTER_SCHEMA,
        )
        try:
            roster_result = _extract_json(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM returned invalid JSON for roster: {exc}\nRaw: {raw[:500]}") from exc

    if isinstance(roster_result, list):
        roster_result = {"book_summary": None, "characters": roster_result}
    if not isinstance(roster_result, dict):
        raise RuntimeError(f"Expected a JSON object from LLM, got: {type(roster_result)}")
    characters_data = roster_result.get("characters")
    if not isinstance(characters_data, list):
        raise RuntimeError(f"Expected a JSON array from LLM, got: {type(characters_data)}")

    grounding_corpus = " ".join(combined_text.split()).casefold()
    grounding_corpus += " " + " ".join(
        " ".join(str(candidate.get("evidence") or "").split()).casefold() for candidate in confirmed_speakers
    )

    def grounded_evidence(items: Any) -> list[str]:
        if not isinstance(items, list):
            return []
        grounded = []
        for item in items:
            value = " ".join(str(item).split()).strip(' "“”')
            if len(value) >= 8 and value.casefold() in grounding_corpus:
                grounded.append(value)
        return grounded[:3]

    # Normalise keys to match our model
    normalised: list[dict] = []
    for c in characters_data:
        if not isinstance(c, dict):
            continue
        description = c.get("description")
        normalised.append(
            {
                "name": str(c.get("name", "Unknown")),
                "aliases": [str(alias) for alias in c.get("aliases", []) if alias],
                "description": description,
                "evidence": grounded_evidence(c.get("evidence")),
                "voice_design_prompt": c.get("voice_design_prompt"),
                "is_narrator": str(c.get("name", "")).strip().casefold() == "narrator",
                "_is_protagonist": bool(re.search(r"\b(?:protagonist|first-person)\b", str(description or ""), re.IGNORECASE)),
            }
        )
    if not normalised:
        raise RuntimeError("LLM returned an empty character roster.")
    existing_names = {character["name"].strip().casefold() for character in normalised}
    promoted_protagonists: list[dict] = []
    for character in normalised:
        if not character["is_narrator"]:
            continue
        retained_aliases = []
        for alias in character["aliases"]:
            canonical = alias.strip().casefold()
            if canonical in {"narrator", "narrative voice", "storyteller"}:
                continue
            if " " in alias.strip() and canonical not in existing_names:
                promoted_protagonists.append(
                    {
                        "name": alias.strip(),
                        "aliases": [],
                        "description": "First-person protagonist, kept separate from the narrative prose voice.",
                        "evidence": character["evidence"],
                        "voice_design_prompt": "[gender-male][pitch-medium][speed-normal]",
                        "is_narrator": False,
                        "_is_protagonist": True,
                    }
                )
                existing_names.add(canonical)
            else:
                retained_aliases.append(alias)
        character["aliases"] = retained_aliases
    for character in normalised:
        if not character["is_narrator"]:
            character["aliases"] = [alias for alias in character["aliases"] if alias.strip().casefold() != "narrator"]
    if not any(character["is_narrator"] for character in normalised):
        normalised.insert(
            0,
            {
                "name": "Narrator",
                "aliases": [],
                "description": "Primary narrative voice.",
                "evidence": [],
                "voice_design_prompt": "[gender-neutral][pitch-medium][speed-normal]",
                "is_narrator": True,
                "_is_protagonist": False,
            },
        )
    for character in normalised:
        if character["is_narrator"]:
            character["name"] = "Narrator"
            character["aliases"] = []
            character["description"] = "Primary narrative voice for prose; not a story character."
            character["evidence"] = []
            character["_is_protagonist"] = False
    if promoted_protagonists:
        narrator_index = next(index for index, character in enumerate(normalised) if character["is_narrator"])
        for offset, protagonist in enumerate(promoted_protagonists, start=1):
            normalised.insert(narrator_index + offset, protagonist)

    normalised = _canonicalize_roster_characters(normalised, confirmed_speakers, grounding_corpus)
    if first_person_gender:
        for character in normalised:
            if character.get("_is_protagonist"):
                character["voice_design_prompt"] = _normalise_voice_prompt(
                    character.get("voice_design_prompt"), gender=first_person_gender
                )
                character["description"] = (
                    "First-person protagonist; spoken dialogue voice is separate from the Narrator. "
                    f"{character['description']}"
                )

    def character_tokens(character: dict) -> set[str]:
        values = [character["name"], *character["aliases"]]
        return {token.casefold() for value in values for token in _CANDIDATE_TOKEN_RE.findall(value)}

    represented_names = {
        value.strip().casefold() for character in normalised for value in [character["name"], *character["aliases"]]
    }
    required_speakers = [candidate for candidate in confirmed_speakers if candidate.get("required", True)][:16]
    for candidate in required_speakers:
        candidate_name = str(candidate.get("canonical_name") or candidate["name"])
        canonical = candidate_name.casefold()
        if canonical in represented_names:
            continue
        normalised.append(
            {
                "name": candidate_name,
                "aliases": [candidate["name"]] if candidate["name"].casefold() != canonical else [],
                "description": (
                    f"Recurring speaking character identified from {candidate['dialogue_count']} explicit "
                    f"dialogue attributions and {candidate['mention_count']} name mentions."
                ),
                "evidence": [candidate["evidence"]] if candidate["evidence"] else [],
                "voice_design_prompt": _normalise_voice_prompt(None, gender=candidate.get("gender") or "neutral"),
                "is_narrator": False,
                "_is_protagonist": False,
            }
        )
        represented_names.update({canonical, candidate["name"].casefold()})

    protagonist_names = {character["name"].strip().casefold() for character in promoted_protagonists}
    if protagonist_names:
        for character in normalised:
            if character["name"].strip().casefold() in protagonist_names:
                continue
            character["aliases"] = [
                alias for alias in character["aliases"] if alias.strip().casefold() not in protagonist_names
            ]

    dialogue_scores = {
        name.casefold(): candidate["dialogue_count"]
        for candidate in confirmed_speakers
        for name in {candidate["name"], candidate.get("canonical_name") or candidate["name"]}
    }

    def roster_priority(character: dict) -> tuple[int, int, str]:
        if character["is_narrator"]:
            return (3, 0, character["name"])
        if character.get("_is_protagonist"):
            return (2, 0, character["name"])
        score = max((dialogue_scores.get(token, 0) for token in character_tokens(character)), default=0)
        return (1, score, character["name"])

    normalised.sort(key=roster_priority, reverse=True)

    if provider != STUB_PROVIDER:
        # Reserve stable voices for one-scene and unnamed dialogue without
        # allowing hundreds of cameos to crowd recurring characters out.
        normalised = normalised[:18]
        normalised.extend(
            [
                {
                    "name": "Minor Female Voice",
                    "aliases": ["Unnamed female speaker"],
                    "description": "Fallback voice for unnamed or one-scene female dialogue.",
                    "evidence": [],
                    "voice_design_prompt": "[gender-female][pitch-medium][speed-normal]",
                    "is_narrator": False,
                    "_is_protagonist": False,
                },
                {
                    "name": "Minor Male Voice",
                    "aliases": ["Unnamed male speaker"],
                    "description": "Fallback voice for unnamed or one-scene male dialogue.",
                    "evidence": [],
                    "voice_design_prompt": "[gender-male][pitch-medium][speed-normal]",
                    "is_narrator": False,
                    "_is_protagonist": False,
                },
            ]
        )

    shared_by_name = {profile.canonical_name: profile for profile in series_profiles}
    for character in normalised:
        profile = shared_by_name.get(" ".join(character["name"].casefold().split()))
        if profile is None:
            continue
        if refresh_series_metadata:
            character["series_character_id"] = profile.id
        else:
            character.update(
                {
                    "series_character_id": profile.id,
                    "name": profile.name,
                    "description": profile.description,
                    "voice_design_prompt": profile.voice_design_prompt,
                    "is_narrator": profile.is_narrator,
                    "aliases": profile.aliases or [],
                    "evidence": profile.evidence or [],
                }
            )

    for character in normalised:
        character.pop("_is_protagonist", None)

    await crud.audiobook.delete_characters_for_book(db, book_id)
    created_characters = await crud.audiobook.create_characters_bulk(
        db,
        book_id=book_id,
        characters_data=normalised[:20],
    )
    if book.series:
        await crud.audiobook.sync_book_roster_with_series(
            db,
            book,
            created_characters,
            prefer_series=not refresh_series_metadata,
        )
        if refresh_series_metadata:
            await crud.audiobook.delete_orphaned_series_characters(db, book.series)
    await crud.audiobook.set_book_audiobook_summary(db, book_id, roster_result.get("book_summary"))
    await crud.audiobook.update_book_pipeline_progress(
        db, book_id, current=1, total=1, detail=f"Created {len(normalised[:20])} character profiles"
    )
    logger.info("Created %d characters for book %s.", len(normalised), book_id)
    if not await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
        await crud.audiobook.set_book_pipeline_status(db, book_id, "diarizing")


async def diarize_sentences(book_id: int, db: AsyncSession) -> None:
    """Phase 3: batch-assign speakers and expression tags to all pending sentences."""
    settings = await crud.audiobook.get_audiobook_settings(db)
    provider = (settings.llm_provider or STUB_PROVIDER).lower() if settings else STUB_PROVIDER

    characters = await crud.audiobook.get_characters_for_book(db, book_id)
    character_ids = {character.id for character in characters}
    narrator_id = next((character.id for character in characters if character.is_narrator), None)
    protagonist_id = next(
        (
            character.id
            for character in characters
            if "first-person protagonist" in str(character.description or "").casefold()
        ),
        None,
    )
    minor_female_id = next((character.id for character in characters if character.name == "Minor Female Voice"), None)
    minor_male_id = next((character.id for character in characters if character.name == "Minor Male Voice"), None)
    roster_json = json.dumps(
        [
            {
                "id": c.id,
                "name": c.name,
                "aliases": c.aliases or [],
                "description": c.description,
                "is_narrator": c.is_narrator,
            }
            for c in characters
        ],
        ensure_ascii=False,
    )

    chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    counts = await crud.audiobook.count_sentences_by_status(db, book_id)
    total = sum(counts.values())
    processed = total - counts.get("pending_diarization", 0)
    batch_size = MAX_DIARIZATION_BATCH_SIZE
    smaller_batch_successes = 0
    await crud.audiobook.update_book_pipeline_progress(
        db, book_id, current=processed, total=total, detail="Preparing dialogue attribution"
    )

    story_started = False
    for chapter_index, chapter in enumerate(chapters, start=1):
        if await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
            logger.info("Book %s paused during diarization.", book_id)
            return

        chapter_sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        pending = [sentence for sentence in chapter_sentences if sentence.status == "pending_diarization"]
        if not pending:
            continue

        # Treat short files before the first substantial chapter as front matter.
        # Once the story begins, retain short chapters and only skip tiny dividers.
        if len(chapter_sentences) >= MIN_STORY_CHAPTER_SENTENCES:
            story_started = True
        is_front_matter = (not story_started and len(chapter_sentences) < MIN_STORY_CHAPTER_SENTENCES) or len(
            chapter_sentences
        ) < 20
        if is_front_matter:
            for sentence in pending:
                await crud.audiobook.update_sentence_diarization(
                    db,
                    sentence.id,
                    narrator_id,
                    sentence.original_text,
                    speaker_confidence=0.99,
                    speaker_reason="Front matter narration",
                )
            processed += len(pending)
            await crud.audiobook.update_chapter_summary(db, chapter.id, "Front matter or section divider.")
            await crud.audiobook.update_book_pipeline_progress(
                db,
                book_id,
                current=processed,
                total=total,
                detail=f"Skipped front matter; next is chapter {chapter.chapter_number}",
            )
            continue

        context_window = [
            sentence.original_text for sentence in chapter_sentences if sentence.status != "pending_diarization"
        ][-8:]
        open_dialogue_speaker_id = None
        for previous_sentence in chapter_sentences:
            if previous_sentence.status == "pending_diarization":
                break
            open_dialogue_speaker_id = _advance_open_dialogue_speaker(
                previous_sentence.original_text,
                previous_sentence.character_id,
                narrator_id=narrator_id,
                minor_female_id=minor_female_id,
                minor_male_id=minor_male_id,
                current_open_speaker_id=open_dialogue_speaker_id,
            )
        while True:
            batch = await crud.audiobook.get_sentences_pending_diarization(
                db, book_id, limit=batch_size, chapter_id=chapter.id
            )
            if not batch:
                break

            sentences_json = json.dumps(
                [{"id": s.id, "text": s.original_text} for s in batch],
                ensure_ascii=False,
            )
            context_str = "\n".join(context_window[-8:]) if context_window else "(none)"

            await crud.audiobook.update_book_pipeline_progress(
                db,
                book_id,
                current=processed,
                total=total,
                detail=(
                    f"Chapter {chapter.chapter_number} ({chapter_index}/{len(chapters)}): "
                    f"attributing {len(batch)} sentences"
                ),
            )
            if provider == STUB_PROVIDER:
                batch_result = {
                    "assignments": [
                        {
                            "id": sentence.id,
                            "character_id": narrator_id,
                            "tagged_text": sentence.original_text,
                            "confidence": 1.0,
                            "reason": "Deterministic local harness",
                        }
                        for sentence in batch
                    ],
                    "chapter_summary": "Deterministic local harness chapter summary.",
                }
            else:
                prompt_template = settings.diarization_prompt_template or DEFAULT_DIARIZATION_PROMPT
                prompt = prompt_template.format(
                    roster_json=roster_json,
                    chapter_summary=chapter.summary or "(none yet)",
                    context=context_str,
                    sentences_json=sentences_json,
                )
                logger.debug("Diarizing %d sentences for book %s.", len(batch), book_id)
                await crud.audiobook.update_book_pipeline_progress(
                    db,
                    book_id,
                    current=processed,
                    total=total,
                    detail=f"Waiting for {settings.llm_model or provider}: chapter {chapter.chapter_number}",
                    llm_request_increment=1,
                )
                raw = await _call_llm(
                    settings,
                    [{"role": "user", "content": prompt}],
                    response_schema=DIARIZATION_SCHEMA,
                )
                try:
                    batch_result = _extract_json(raw)
                except json.JSONDecodeError as exc:
                    if batch_size > MIN_DIARIZATION_BATCH_SIZE:
                        smaller_batch_size = max(MIN_DIARIZATION_BATCH_SIZE, batch_size // 2)
                        logger.warning(
                            "Invalid diarization JSON for book %s at batch size %s; retrying %s sentences: %s",
                            book_id,
                            batch_size,
                            smaller_batch_size,
                            exc,
                        )
                        batch_size = smaller_batch_size
                        smaller_batch_successes = 0
                        await crud.audiobook.update_book_pipeline_progress(
                            db,
                            book_id,
                            current=processed,
                            total=total,
                            detail=f"Retrying malformed model output with {batch_size} sentences",
                        )
                        continue
                    raw_excerpt = f"{raw[:500]}\n...\n{raw[-500:]}" if len(raw) > 1000 else raw
                    raise RuntimeError(
                        f"LLM returned invalid JSON for diarization after smaller-batch retries: {exc}\n" f"Raw: {raw_excerpt}"
                    ) from exc

            try:
                batch_result = _normalise_diarization_result(
                    batch_result,
                    {sentence.id for sentence in batch},
                )
            except ValueError as exc:
                if provider != STUB_PROVIDER and batch_size > MIN_DIARIZATION_BATCH_SIZE:
                    smaller_batch_size = max(MIN_DIARIZATION_BATCH_SIZE, batch_size // 2)
                    logger.warning(
                        "Incomplete diarization response for book %s at batch size %s; retrying %s sentences: %s",
                        book_id,
                        batch_size,
                        smaller_batch_size,
                        exc,
                    )
                    batch_size = smaller_batch_size
                    smaller_batch_successes = 0
                    await crud.audiobook.update_book_pipeline_progress(
                        db,
                        book_id,
                        current=processed,
                        total=total,
                        detail=f"Retrying incomplete model output with {batch_size} sentences",
                    )
                    continue
                raise RuntimeError(f"Invalid diarization response: {exc}") from exc

            if batch_size < MAX_DIARIZATION_BATCH_SIZE:
                smaller_batch_successes += 1
                if smaller_batch_successes >= 2:
                    batch_size = min(MAX_DIARIZATION_BATCH_SIZE, batch_size * 2)
                    smaller_batch_successes = 0
            results = batch_result["assignments"]

            result_map = {r["id"]: r for r in results if isinstance(r, dict) and isinstance(r.get("id"), int)}

            for sentence_index, sentence in enumerate(batch):
                result = result_map.get(sentence.id, {})
                char_id = result.get("character_id")
                if char_id not in character_ids:
                    char_id = narrator_id
                tagged = _sanitize_tagged_text(sentence.original_text, result.get("tagged_text"))
                confidence = result.get("confidence")
                try:
                    confidence = max(0.0, min(1.0, float(confidence)))
                except (TypeError, ValueError):
                    confidence = 0.0
                reason = str(result.get("reason") or "No model rationale returned")[:500]
                next_text = batch[sentence_index + 1].original_text if sentence_index + 1 < len(batch) else ""
                char_id, reason, guardrail_confidence = _apply_speaker_guardrails(
                    text=sentence.original_text,
                    next_text=next_text,
                    character_id=char_id,
                    narrator_id=narrator_id,
                    protagonist_id=protagonist_id,
                    minor_female_id=minor_female_id,
                    minor_male_id=minor_male_id,
                    reason=reason,
                )
                if guardrail_confidence is not None:
                    confidence = guardrail_confidence
                if open_dialogue_speaker_id is not None and char_id == narrator_id:
                    char_id = open_dialogue_speaker_id
                    reason = "Deterministic continuation of open quoted dialogue"
                    confidence = 0.95
                open_dialogue_speaker_id = _advance_open_dialogue_speaker(
                    sentence.original_text,
                    char_id,
                    narrator_id=narrator_id,
                    minor_female_id=minor_female_id,
                    minor_male_id=minor_male_id,
                    current_open_speaker_id=open_dialogue_speaker_id,
                )
                await crud.audiobook.update_sentence_diarization(
                    db,
                    sentence.id,
                    char_id,
                    tagged,
                    speaker_confidence=confidence,
                    speaker_reason=reason,
                )
                context_window.append(sentence.original_text)

            chapter_summary = str(batch_result.get("chapter_summary") or chapter.summary or "")[:1200]
            await crud.audiobook.update_chapter_summary(db, chapter.id, chapter_summary or None)
            chapter.summary = chapter_summary or None
            processed += len(batch)
            await crud.audiobook.update_book_pipeline_progress(
                db,
                book_id,
                current=processed,
                total=total,
                detail=f"Chapter {chapter.chapter_number}: attributed {processed} of {total} sentences",
            )
            if await crud.audiobook.consume_book_batch_limit(db, book_id):
                logger.info("Book %s paused after one diarization batch.", book_id)
                return

    logger.info("Diarization complete for book %s.", book_id)
    if not await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
        await crud.audiobook.set_book_pipeline_status(db, book_id, "audio_gen")
