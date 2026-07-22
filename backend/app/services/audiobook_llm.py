"""Phases 2 & 3: LLM-based character roster generation and sentence diarization."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..models import AudiobookSettings, Book

logger = logging.getLogger(__name__)

STUB_PROVIDER = "stub"
DIARIZATION_BATCH_SIZE = 40
STORY_CHAPTER_MIN_SENTENCES = 40

DEFAULT_ROSTER_PROMPT = """\
You are a literary analyst preparing a cast list for an audiobook. Analyze the sampled excerpts from across the \
book and identify the primary narrator plus the major or recurring speaking characters. Merge aliases, titles, and \
surname-only references into one character. Do not include authors, publishers, places, organizations, unnamed \
crowds, or one-line background figures. Prefer people with repeated mentions across the book and omit one-scene \
figures even if they appear in an excerpt. Return no more than 15 characters.

For each character produce:
- name: canonical full name; use "Narrator" for the narrative prose voice
- aliases: other names, surnames, nicknames, ranks, or titles used for this person
- description: a concise description of their personality, relationships, and role
- evidence: 1-3 short quotations or explicit textual facts supporting the identification
- voice_prompt: a provider-neutral voice profile using ONLY these tokens:
  [gender-{{male|female|neutral}}] [pitch-{{low|medium|high}}] [speed-{{slow|normal|fast}}]
  Optional: [accent-{{british|american|australian}}] [age-{{young|middle|old}}]
  Example: [gender-male][pitch-low][speed-normal][age-middle]
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

Sentences to process (JSON array with id, text, and its immediate previous/next context):
{sentences_json}

For each sentence return (exactly {assignment_count} assignments total, one per input sentence in the same order;
do not omit or duplicate an id). Assign only the `text`; use `previous_text` and `next_text` solely to resolve
speaker attribution:
- i: the sentence id (integer)
- c: the character id from the roster (use the narrator's id for narration; null if uncertain)
- e: one of "laughter", "sigh", "whisper", "shout", or null. Do not repeat the sentence text.

Return minified, single-line JSON with the key assignments. Do not add whitespace, markdown, explanation, repeated
sentence text, or chapter summary.
"""

_ALLOWED_EXPRESSION_TAGS = {"laughter", "sigh", "whisper", "shout"}
_BRACKET_TAG_RE = re.compile(r"\[([^\[\]]+)\]")
_GENDERED_ATTRIBUTION_RE = re.compile(
    r"\b(she|he)\s+(?:said|asked|replied|yelled|shouted|whispered|muttered|added|continued|answered|snapped)\b",
    re.IGNORECASE,
)
_NARRATION_REASON_RE = re.compile(
    r"\b(?:narrat(?:or|ion|ive)|internal|reflection|action description|monologue|observation|recounting)\b",
    re.IGNORECASE,
)
_DIARIZATION_REASON_LABELS = {
    "explicit_attribution": "Explicit dialogue attribution",
    "adjacent_attribution": "Adjacent dialogue attribution",
    "turn_taking": "Conversational turn-taking",
    "narration": "Narrative prose",
    "minor_speaker": "Unnamed or one-scene speaker",
    "uncertain": "Model was uncertain",
}

ROSTER_SCHEMA = {
    "type": "object",
    "properties": {
        "book_summary": {"type": "string"},
        "characters": {
            "type": "array",
            "maxItems": 15,
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
                    "voice_prompt": {"type": "string"},
                    "is_narrator": {"type": "boolean"},
                },
                "required": [
                    "name",
                    "aliases",
                    "description",
                    "evidence",
                    "voice_prompt",
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
                    "i": {"type": "integer"},
                    "c": {"type": ["integer", "null"]},
                    "e": {
                        "type": ["string", "null"],
                        "enum": [None, "laughter", "sigh", "whisper", "shout"],
                    },
                },
                "required": ["i", "c", "e"],
            },
        },
    },
    "required": ["assignments"],
}


def _diarization_schema(assignment_count: int) -> dict[str, Any]:
    """Constrain structured output to one result per requested sentence."""
    schema = copy.deepcopy(DIARIZATION_SCHEMA)
    assignments = schema["properties"]["assignments"]
    assignments["minItems"] = assignment_count
    assignments["maxItems"] = assignment_count
    return schema


def _sentence_ids_requiring_diarization(sentences: list[Any]) -> set[int]:
    """Keep quoted spans for the model; prose outside them is narrator-owned."""
    in_dialogue = False
    requiring_model: set[int] = set()
    for sentence in sentences:
        starts_in_dialogue = in_dialogue
        contains_quote = False
        for character in sentence.original_text:
            if character == "“":
                in_dialogue = True
                contains_quote = True
            elif character == "”":
                in_dialogue = False
                contains_quote = True
            elif character == '"':
                in_dialogue = not in_dialogue
                contains_quote = True
        if starts_in_dialogue or contains_quote or in_dialogue:
            requiring_model.add(sentence.id)
    return requiring_model


CHAPTER_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 1200},
    },
    "required": ["summary"],
}


async def _call_llm(
    settings: AudiobookSettings,
    messages: list[dict[str, Any]],
    *,
    response_schema: dict[str, Any] | None = None,
    progress_callback: Callable[[int], Awaitable[None]] | None = None,
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
            "stream": progress_callback is not None,
            "think": False,
            "format": response_schema or "json",
            # A structured batch response can legitimately exceed 4K tokens.
            # Keep enough headroom to close the JSON document; the
            # diarization loop also shrinks the batch if a provider still
            # returns malformed or incomplete output.
            "options": {"temperature": 0, "num_ctx": 32768, "num_predict": 8192},
            "keep_alive": "30m",
        }
        timeout = httpx.Timeout(600.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if progress_callback is not None:
                chunks: list[str] = []
                received_chars = 0
                last_reported_chars = 0
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.is_error:
                        await resp.aread()
                        resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            logger.warning("Ignoring malformed Ollama stream event: %s", line[:200])
                            continue
                        content = event.get("message", {}).get("content") or ""
                        if content:
                            chunks.append(content)
                            received_chars += len(content)
                        if received_chars - last_reported_chars >= 1024 or event.get("done"):
                            await progress_callback(received_chars)
                            last_reported_chars = received_chars
                return "".join(chunks)
            resp = await client.post(url, json=payload, headers=headers)
            if resp.is_error:
                resp.raise_for_status()
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


def _extract_json(raw: str) -> Any:
    """Strip markdown code fences if present and parse JSON."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first and last fence lines
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(text)


class _DiarizationResponseError(ValueError):
    """The model response cannot safely be applied to a diarization batch."""


def _salvage_complete_assignments(raw: str) -> list[dict[str, Any]]:
    """Recover complete assignment objects from a truncated JSON array."""
    match = re.search(r'"assignments"\s*:\s*\[', raw)
    if match is None:
        return []

    assignments: list[dict[str, Any]] = []
    object_start: int | None = None
    object_depth = 0
    in_string = False
    escaped = False
    for index in range(match.end(), len(raw)):
        char = raw[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if object_depth == 0:
                object_start = index
            object_depth += 1
            continue
        if char != "}" or object_depth == 0:
            continue
        object_depth -= 1
        if object_depth or object_start is None:
            continue
        object_end = index + 1
        try:
            assignment = json.loads(raw[object_start:object_end])
        except json.JSONDecodeError:
            object_start = None
            continue
        if isinstance(assignment, dict):
            assignments.append(assignment)
        object_start = None
    return assignments


def _parse_diarization_response(
    raw: str,
    expected_ids: list[int],
) -> tuple[dict[str, Any], set[int], bool]:
    """Parse, de-duplicate, and salvage any safe diarization assignments."""
    salvaged = False
    try:
        result = _extract_json(raw)
    except json.JSONDecodeError as exc:
        assignments = _salvage_complete_assignments(raw)
        if not assignments:
            raise _DiarizationResponseError(str(exc)) from exc
        result = {"assignments": assignments, "chapter_summary": None}
        salvaged = True

    if isinstance(result, list):
        result = {"assignments": result, "chapter_summary": None}
    if not isinstance(result, dict) or not isinstance(result.get("assignments"), list):
        raise _DiarizationResponseError(f"expected an assignments array, got {type(result).__name__}")

    expected_id_set = set(expected_ids)
    by_id: dict[int, dict[str, Any]] = {}
    for assignment in result["assignments"]:
        if not isinstance(assignment, dict):
            continue
        sentence_id = assignment.get("id", assignment.get("i"))
        if not isinstance(sentence_id, int) or sentence_id not in expected_id_set:
            continue
        normalized = {
            **assignment,
            "id": sentence_id,
            "character_id": assignment.get(
                "character_id",
                assignment.get("c"),
            ),
            "expression": assignment.get(
                "expression",
                assignment.get("e"),
            ),
        }
        current = by_id.get(sentence_id)
        try:
            candidate_confidence = float(normalized.get("confidence") or 0)
        except (TypeError, ValueError):
            candidate_confidence = 0
        try:
            current_confidence = float(current.get("confidence") or 0) if current else -1
        except (TypeError, ValueError):
            current_confidence = 0
        if current is None or candidate_confidence >= current_confidence:
            by_id[sentence_id] = normalized

    if not by_id:
        raise _DiarizationResponseError("response did not contain any requested sentence ids")

    result["assignments"] = [by_id[sentence_id] for sentence_id in expected_ids if sentence_id in by_id]
    missing_ids = expected_id_set - set(by_id)
    return result, missing_ids, salvaged


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
    minor_female_id: int | None,
    minor_male_id: int | None,
    reason: str,
) -> tuple[int | None, str, float | None]:
    """Correct two common local-model ID errors without inventing named speakers."""
    has_closing_quote = "”" in text or ('"' in text and not text.rstrip().endswith('"'))
    starts_with_quote = text.lstrip().startswith(("“", '"'))
    has_dialogue = has_closing_quote or starts_with_quote

    if character_id == narrator_id and has_dialogue:
        attribution = _GENDERED_ATTRIBUTION_RE.search(f"{text} {next_text}")
        if attribution:
            gender = attribution.group(1).casefold()
            fallback_id = minor_female_id if gender == "she" else minor_male_id
            if fallback_id is not None:
                return fallback_id, f"Deterministic {gender} dialogue attribution to minor voice", 0.98

    if character_id != narrator_id and not has_dialogue and _NARRATION_REASON_RE.search(reason):
        return narrator_id, "Deterministic prose/narration guardrail", 0.98

    return character_id, reason, None


async def _build_roster_excerpt(chapters, db: AsyncSession) -> str:
    """Sample real story chapters across the book instead of front matter."""
    candidates: list[tuple[Any, list[Any]]] = []
    for chapter in chapters:
        sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        if len(sentences) >= 40:
            candidates.append((chapter, sentences))

    if not candidates:
        for chapter in chapters:
            sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
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


async def _build_character_candidate_analysis(chapters, db: AsyncSession) -> tuple[str, list[dict[str, Any]]]:
    """Provide whole-book evidence so sampled cameos do not crowd out recurring cast."""
    counts: Counter[str] = Counter()
    contextual_counts: Counter[str] = Counter()
    dialogue_counts: Counter[str] = Counter()
    dialogue_examples: dict[str, str] = {}
    for chapter in chapters:
        for sentence in await crud.audiobook.get_sentences_for_chapter(db, chapter.id):
            for match in _CANDIDATE_TOKEN_RE.finditer(sentence.original_text):
                token = match.group(0)
                if token in _CANDIDATE_STOP_WORDS:
                    continue
                counts[token] += 1
                if match.start() > 0:
                    contextual_counts[token] += 1
            for match in _DIALOGUE_TAG_RE.finditer(sentence.original_text):
                name = match.group(1) or match.group(2)
                if name in _CANDIDATE_STOP_WORDS:
                    continue
                dialogue_counts[name] += 1
                dialogue_examples.setdefault(name, sentence.original_text[:220])

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
    confirmed = [
        {
            "name": name,
            "mention_count": count,
            "dialogue_count": dialogue_count,
            "evidence": dialogue_examples.get(name),
        }
        for name, count, _, dialogue_count in candidates
        if dialogue_count >= 5
    ]
    required_names = ", ".join(candidate["name"] for candidate in confirmed[:12])
    heading = f"REQUIRED confirmed speakers (include all): {required_names}\n" if required_names else ""
    return heading + ("\n".join(lines) or "(none)"), confirmed


async def _build_character_candidate_hints(chapters, db: AsyncSession) -> str:
    hints, _ = await _build_character_candidate_analysis(chapters, db)
    return hints


async def generate_character_roster(book_id: int, db: AsyncSession) -> None:
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
    series_roster = (
        json.dumps(
            [
                {
                    "name": profile.name,
                    "aliases": profile.aliases or [],
                    "description": profile.description,
                    "voice_prompt": profile.voice_prompt,
                    "tts_voice_id": profile.tts_voice_id,
                    "tts_voice_provider": profile.tts_voice_provider,
                }
                for profile in series_profiles
            ],
            ensure_ascii=False,
        )
        if series_profiles
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
                    "voice_prompt": "[gender-neutral][pitch-medium][speed-normal]",
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

    # Normalise keys to match our model
    normalised: list[dict] = []
    for c in characters_data:
        if not isinstance(c, dict):
            continue
        normalised.append(
            {
                "name": str(c.get("name", "Unknown")),
                "aliases": [str(alias) for alias in c.get("aliases", []) if alias],
                "description": c.get("description"),
                "evidence": [str(item) for item in c.get("evidence", []) if item][:3],
                "voice_prompt": c.get("voice_prompt"),
                "is_narrator": str(c.get("name", "")).strip().casefold() == "narrator",
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
                        "voice_prompt": "[gender-male][pitch-medium][speed-normal]",
                        "is_narrator": False,
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
                "voice_prompt": "[gender-neutral][pitch-medium][speed-normal]",
                "is_narrator": True,
            },
        )
    if promoted_protagonists:
        narrator_index = next(index for index, character in enumerate(normalised) if character["is_narrator"])
        for offset, protagonist in enumerate(promoted_protagonists, start=1):
            normalised.insert(narrator_index + offset, protagonist)

    def character_tokens(character: dict) -> set[str]:
        values = [character["name"], *character["aliases"]]
        return {token.casefold() for value in values for token in _CANDIDATE_TOKEN_RE.findall(value)}

    represented_tokens = set().union(*(character_tokens(character) for character in normalised))
    for candidate in confirmed_speakers[:12]:
        canonical = candidate["name"].casefold()
        if canonical in represented_tokens:
            continue
        normalised.append(
            {
                "name": candidate["name"],
                "aliases": [],
                "description": (
                    f"Recurring speaking character identified from {candidate['dialogue_count']} explicit "
                    "dialogue attributions across the book."
                ),
                "evidence": [candidate["evidence"]] if candidate["evidence"] else [],
                "voice_prompt": "[gender-neutral][pitch-medium][speed-normal]",
                "is_narrator": False,
            }
        )
        represented_tokens.add(canonical)

    protagonist_names = {character["name"].strip().casefold() for character in promoted_protagonists}
    if protagonist_names:
        for character in normalised:
            if character["name"].strip().casefold() in protagonist_names:
                continue
            character["aliases"] = [
                alias for alias in character["aliases"] if alias.strip().casefold() not in protagonist_names
            ]

    dialogue_scores = {candidate["name"].casefold(): candidate["dialogue_count"] for candidate in confirmed_speakers}

    def roster_priority(character: dict) -> tuple[int, int, str]:
        if character["is_narrator"]:
            return (3, 0, character["name"])
        if "protagonist" in str(character.get("description") or "").casefold():
            return (2, 0, character["name"])
        score = max((dialogue_scores.get(token, 0) for token in character_tokens(character)), default=0)
        return (1, score, character["name"])

    normalised.sort(key=roster_priority, reverse=True)

    if provider != STUB_PROVIDER:
        # Reserve stable voices for one-scene and unnamed dialogue without
        # allowing hundreds of cameos to crowd recurring characters out.
        normalised = normalised[:13]
        normalised.extend(
            [
                {
                    "name": "Minor Female Voice",
                    "aliases": ["Unnamed female speaker"],
                    "description": "Fallback voice for unnamed or one-scene female dialogue.",
                    "evidence": [],
                    "voice_prompt": "[gender-female][pitch-medium][speed-normal]",
                    "is_narrator": False,
                },
                {
                    "name": "Minor Male Voice",
                    "aliases": ["Unnamed male speaker"],
                    "description": "Fallback voice for unnamed or one-scene male dialogue.",
                    "evidence": [],
                    "voice_prompt": "[gender-male][pitch-medium][speed-normal]",
                    "is_narrator": False,
                },
            ]
        )

    shared_by_name = {profile.canonical_name: profile for profile in series_profiles}
    for character in normalised:
        profile = shared_by_name.get(" ".join(character["name"].casefold().split()))
        if profile is None:
            continue
        character.update(
            {
                "series_character_id": profile.id,
                "name": profile.name,
                "description": profile.description,
                "voice_prompt": profile.voice_prompt,
                "tts_voice_id": profile.tts_voice_id,
                "tts_voice_provider": profile.tts_voice_provider,
                "is_narrator": profile.is_narrator,
                "aliases": profile.aliases or [],
                "evidence": profile.evidence or [],
            }
        )

    await crud.audiobook.delete_characters_for_book(db, book_id)
    created_characters = await crud.audiobook.create_characters_bulk(
        db,
        book_id=book_id,
        characters_data=normalised[:15],
    )
    if book.series:
        await crud.audiobook.sync_book_roster_with_series(
            db,
            book,
            created_characters,
            prefer_series=True,
        )
    await crud.audiobook.set_book_audiobook_summary(db, book_id, roster_result.get("book_summary"))
    await crud.audiobook.update_book_pipeline_progress(
        db, book_id, current=1, total=1, detail=f"Created {len(normalised[:15])} character profiles"
    )
    logger.info("Created %d characters for book %s.", len(normalised), book_id)
    if not await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
        await crud.audiobook.set_book_pipeline_status(db, book_id, "diarizing")


def _chapter_summary_excerpt(chapter_sentences: list[Any], max_chars: int = 12_000) -> str:
    """Sample contiguous beginning, middle, and ending text for one summary call."""
    texts = [sentence.original_text for sentence in chapter_sentences if sentence.original_text.strip()]
    complete = "\n".join(texts)
    if len(complete) <= max_chars:
        return complete

    section_chars = max_chars // 3

    def take_section(section: list[str], *, reverse: bool = False) -> str:
        selected = []
        used = 0
        items = reversed(section) if reverse else iter(section)
        for text in items:
            if selected and used + len(text) + 1 > section_chars:
                break
            selected.append(text)
            used += len(text) + 1
        if reverse:
            selected.reverse()
        return "\n".join(selected)

    midpoint = len(texts) // 2
    middle_start = max(0, midpoint - len(texts) // 6)
    return "\n\n[...]\n\n".join(
        [
            take_section(texts),
            take_section(texts[middle_start:]),
            take_section(texts, reverse=True),
        ]
    )


async def _generate_chapter_summary(
    settings: AudiobookSettings,
    chapter: Any,
    chapter_sentences: list[Any],
    db: AsyncSession,
    *,
    book_id: int,
    processed: int,
    total: int,
) -> None:
    """Generate one non-critical chapter summary after attribution completes."""
    excerpt = _chapter_summary_excerpt(chapter_sentences)
    if not excerpt:
        return
    prompt = (
        "Write a spoiler-light 2-4 sentence summary grounded only in the chapter text below. "
        "Do not use character-roster descriptions or outside knowledge. Return JSON with the key summary.\n\n"
        f"Chapter text:\n{excerpt}"
    )
    await crud.audiobook.update_book_pipeline_progress(
        db,
        book_id,
        current=processed,
        total=total,
        detail=f"Summarizing chapter {chapter.chapter_number}",
        llm_request_increment=1,
    )
    try:
        raw = await _call_llm(
            settings,
            [{"role": "user", "content": prompt}],
            response_schema=CHAPTER_SUMMARY_SCHEMA,
        )
        result = _extract_json(raw)
        summary = str(result.get("summary") or "").strip() if isinstance(result, dict) else ""
        if summary:
            await crud.audiobook.update_chapter_summary(db, chapter.id, summary[:4000])
            chapter.summary = summary[:4000]
    except Exception as exc:
        # Summaries help review but are not required to synthesize or assemble
        # the audiobook, so never strand a completed attribution phase here.
        logger.warning(
            "Unable to summarize book %s chapter %s; continuing conversion: %s",
            book_id,
            chapter.chapter_number,
            exc,
        )


async def diarize_sentences(
    book_id: int,
    db: AsyncSession,
    *,
    on_sentences_ready: Callable[[list[int]], Awaitable[None]] | None = None,
) -> None:
    """Phase 3: batch-assign speakers and expression tags to all pending sentences."""
    settings = await crud.audiobook.get_audiobook_settings(db)
    provider = (settings.llm_provider or STUB_PROVIDER).lower() if settings else STUB_PROVIDER

    characters = await crud.audiobook.get_characters_for_book(db, book_id)
    character_ids = {character.id for character in characters}
    narrator_id = next((character.id for character in characters if character.is_narrator), None)
    minor_female_id = next((character.id for character in characters if character.name == "Minor Female Voice"), None)
    minor_male_id = next((character.id for character in characters if character.name == "Minor Male Voice"), None)
    roster_json = json.dumps(
        [{"id": c.id, "name": c.name, "description": c.description, "is_narrator": c.is_narrator} for c in characters],
        ensure_ascii=False,
    )

    chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    counts = await crud.audiobook.count_sentences_by_status(db, book_id)
    total = sum(counts.values())
    processed = total - counts.get("pending_diarization", 0)
    batch_size = DIARIZATION_BATCH_SIZE
    request_batch_size = batch_size
    singleton_parse_failures = 0
    await crud.audiobook.update_book_pipeline_progress(
        db, book_id, current=processed, total=total, detail="Preparing dialogue attribution"
    )

    story_started = False
    for chapter_index, chapter in enumerate(chapters, start=1):
        if await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
            logger.info("Book %s paused during diarization.", book_id)
            return

        chapter_sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        sentence_lengths = {sentence.id: len(sentence.tagged_text or sentence.original_text) for sentence in chapter_sentences}
        pending = [sentence for sentence in chapter_sentences if sentence.status == "pending_diarization"]
        if not pending:
            if provider != STUB_PROVIDER and chapter.summary is None and chapter_sentences:
                await _generate_chapter_summary(
                    settings,
                    chapter,
                    chapter_sentences,
                    db,
                    book_id=book_id,
                    processed=processed,
                    total=total,
                )
            continue

        # Treat short files before the first substantial chapter as front matter.
        # Once the story begins, retain short chapters and only skip tiny dividers.
        if len(chapter_sentences) >= STORY_CHAPTER_MIN_SENTENCES:
            story_started = True
        is_front_matter = (not story_started and len(chapter_sentences) < STORY_CHAPTER_MIN_SENTENCES) or len(
            chapter_sentences
        ) < 20
        if is_front_matter:
            ready_sentence_ids = []
            for sentence in pending:
                await crud.audiobook.update_sentence_diarization(
                    db,
                    sentence.id,
                    narrator_id,
                    sentence.original_text,
                    speaker_confidence=0.99,
                    speaker_reason="Front matter narration",
                )
                ready_sentence_ids.append(sentence.id)
            if on_sentences_ready and ready_sentence_ids:
                ready_sentence_ids.sort(key=sentence_lengths.get)
                await on_sentences_ready(ready_sentence_ids)
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

        if provider != STUB_PROVIDER:
            model_sentence_ids = _sentence_ids_requiring_diarization(chapter_sentences)
            narration_ids = [sentence.id for sentence in pending if sentence.id not in model_sentence_ids]
            if narration_ids:
                narration_ids.sort(key=sentence_lengths.get)
                await crud.audiobook.mark_sentences_as_narration(
                    db,
                    narration_ids,
                    narrator_id,
                )
                if on_sentences_ready:
                    await on_sentences_ready(narration_ids)
                processed += len(narration_ids)
                pending = [sentence for sentence in pending if sentence.id in model_sentence_ids]
                await crud.audiobook.update_book_pipeline_progress(
                    db,
                    book_id,
                    current=processed,
                    total=total,
                    detail=(
                        f"Chapter {chapter.chapter_number}: attributed "
                        f"{len(narration_ids)} deterministic narration sentences"
                    ),
                )

        chapter_positions = {sentence.id: index for index, sentence in enumerate(chapter_sentences)}
        context_window = [
            sentence.original_text for sentence in chapter_sentences if sentence.status != "pending_diarization"
        ][-8:]
        while True:
            if await crud.audiobook.pause_book_pipeline_if_requested(
                db,
                book_id,
            ):
                logger.info(
                    "Book %s paused before the next diarization batch.",
                    book_id,
                )
                return
            batch = await crud.audiobook.get_sentences_pending_diarization(
                db, book_id, limit=request_batch_size, chapter_id=chapter.id
            )
            if not batch:
                break

            sentences_json = json.dumps(
                [
                    {
                        "id": sentence.id,
                        "text": sentence.original_text,
                        "previous_text": (
                            chapter_sentences[chapter_positions[sentence.id] - 1].original_text
                            if chapter_positions[sentence.id] > 0
                            else None
                        ),
                        "next_text": (
                            chapter_sentences[chapter_positions[sentence.id] + 1].original_text
                            if chapter_positions[sentence.id] + 1 < len(chapter_sentences)
                            else None
                        ),
                    }
                    for sentence in batch
                ],
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
                    assignment_count=len(batch),
                )
                logger.debug("Diarizing %d sentences for book %s.", len(batch), book_id)
                raw = None
                for request_attempt in range(1, 4):
                    await crud.audiobook.update_book_pipeline_progress(
                        db,
                        book_id,
                        current=processed,
                        total=total,
                        detail=(
                            f"Waiting for {settings.llm_model or provider}: chapter "
                            f"{chapter.chapter_number}, request {request_attempt}"
                        ),
                        llm_request_increment=1,
                    )
                    try:
                        raw = await _call_llm(
                            settings,
                            [{"role": "user", "content": prompt}],
                            response_schema=_diarization_schema(len(batch)),
                            progress_callback=lambda received_chars: crud.audiobook.update_book_pipeline_progress(
                                db,
                                book_id,
                                current=processed,
                                total=total,
                                detail=(
                                    f"Chapter {chapter.chapter_number}: receiving " f"{received_chars:,} response characters"
                                ),
                            ),
                        )
                        break
                    except httpx.HTTPError as exc:
                        status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else 0
                        if request_attempt == 3 or (status_code and status_code < 500 and status_code != 429):
                            raise
                        logger.warning(
                            "Transient LLM request failure for book %s chapter %s (%d/3): %s",
                            book_id,
                            chapter.chapter_number,
                            request_attempt,
                            exc,
                        )
                        await crud.audiobook.update_book_pipeline_progress(
                            db,
                            book_id,
                            current=processed,
                            total=total,
                            detail=(
                                f"Chapter {chapter.chapter_number}: model connection failed; "
                                f"retrying request {request_attempt + 1} of 3"
                            ),
                        )
                        await asyncio.sleep(2 ** (request_attempt - 1))
                if raw is None:
                    raise RuntimeError("LLM request completed without a response.")
                try:
                    batch_result, missing_ids, salvaged = _parse_diarization_response(
                        raw,
                        [sentence.id for sentence in batch],
                    )
                except _DiarizationResponseError as exc:
                    if len(batch) > 1:
                        request_batch_size = max(1, len(batch) // 2)
                        singleton_parse_failures = 0
                        logger.warning(
                            "Invalid diarization response for book %s chapter %s (%d sentences): %s. "
                            "Retrying with batches of %d.",
                            book_id,
                            chapter.chapter_number,
                            len(batch),
                            exc,
                            request_batch_size,
                        )
                        await crud.audiobook.update_book_pipeline_progress(
                            db,
                            book_id,
                            current=processed,
                            total=total,
                            detail=(
                                f"Model response was incomplete; retrying chapter {chapter.chapter_number} "
                                f"with {request_batch_size}-sentence batches"
                            ),
                        )
                        continue

                    singleton_parse_failures += 1
                    if singleton_parse_failures < 2:
                        logger.warning(
                            "Invalid diarization response for sentence %s: %s. Retrying once.",
                            batch[0].id,
                            exc,
                        )
                        continue
                    logger.error(
                        "Falling back to narrator for sentence %s after repeated invalid model responses: %s",
                        batch[0].id,
                        exc,
                    )
                    batch_result = {
                        "assignments": [
                            {
                                "id": batch[0].id,
                                "character_id": narrator_id,
                                "tagged_text": None,
                                "confidence": 0,
                                "reason": "Fallback after repeated invalid model responses",
                                "_fallback": True,
                            }
                        ],
                        "chapter_summary": chapter.summary,
                    }
                    missing_ids = set()
                    salvaged = False

                if missing_ids:
                    request_batch_size = max(1, min(len(missing_ids), request_batch_size // 2))
                    logger.warning(
                        "Diarization response for book %s chapter %s was %s and omitted %d sentence(s). "
                        "Persisting %d valid assignment(s) and retrying the remainder in batches of %d.",
                        book_id,
                        chapter.chapter_number,
                        "truncated" if salvaged else "incomplete",
                        len(missing_ids),
                        len(batch_result["assignments"]),
                        request_batch_size,
                    )
                elif request_batch_size < batch_size:
                    # A smaller batch succeeded, so cautiously reclaim
                    # throughput instead of throttling the rest of the book
                    # because of one malformed or incomplete response.
                    request_batch_size = min(
                        batch_size,
                        request_batch_size * 2,
                    )

            singleton_parse_failures = 0
            results = batch_result["assignments"]

            result_map = {r["id"]: r for r in results if isinstance(r, dict) and isinstance(r.get("id"), int)}

            completed_count = 0
            ready_sentence_ids = []
            for sentence_index, sentence in enumerate(batch):
                result = result_map.get(sentence.id)
                if result is None:
                    continue
                char_id = result.get("character_id")
                if char_id not in character_ids:
                    char_id = narrator_id
                expression = result.get("expression")
                if expression in _ALLOWED_EXPRESSION_TAGS:
                    tagged = f"[{expression}] {sentence.original_text}"
                else:
                    tagged = _sanitize_tagged_text(sentence.original_text, result.get("tagged_text"))
                confidence = result.get("confidence", 0.9)
                try:
                    confidence = max(0.0, min(1.0, float(confidence)))
                except (TypeError, ValueError):
                    confidence = 0.0
                raw_reason = str(result.get("reason") or "Model speaker assignment")
                reason = _DIARIZATION_REASON_LABELS.get(raw_reason, raw_reason)[:500]
                position = chapter_positions[sentence.id]
                next_text = chapter_sentences[position + 1].original_text if position + 1 < len(chapter_sentences) else ""
                if not result.get("_fallback"):
                    char_id, reason, guardrail_confidence = _apply_speaker_guardrails(
                        text=sentence.original_text,
                        next_text=next_text,
                        character_id=char_id,
                        narrator_id=narrator_id,
                        minor_female_id=minor_female_id,
                        minor_male_id=minor_male_id,
                        reason=reason,
                    )
                    if guardrail_confidence is not None:
                        confidence = guardrail_confidence
                await crud.audiobook.update_sentence_diarization(
                    db,
                    sentence.id,
                    char_id,
                    tagged,
                    speaker_confidence=confidence,
                    speaker_reason=reason,
                )
                context_window.append(sentence.original_text)
                completed_count += 1
                ready_sentence_ids.append(sentence.id)

            if on_sentences_ready and ready_sentence_ids:
                ready_sentence_ids.sort(key=sentence_lengths.get)
                await on_sentences_ready(ready_sentence_ids)

            chapter_summary = str(batch_result.get("chapter_summary") or chapter.summary or "")[:4000]
            await crud.audiobook.update_chapter_summary(db, chapter.id, chapter_summary or None)
            chapter.summary = chapter_summary or None
            processed += completed_count
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

        if provider != STUB_PROVIDER and chapter.summary is None:
            await _generate_chapter_summary(
                settings,
                chapter,
                chapter_sentences,
                db,
                book_id=book_id,
                processed=processed,
                total=total,
            )

    logger.info("Diarization complete for book %s.", book_id)
    if not await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
        await crud.audiobook.set_book_pipeline_status(db, book_id, "audio_gen")
