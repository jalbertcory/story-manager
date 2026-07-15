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
figures even if they appear in an excerpt. Return no more than 15 characters.

For each character produce:
- name: canonical full name; use "Narrator" for the narrative prose voice
- aliases: other names, surnames, nicknames, ranks, or titles used for this person
- description: a concise description of their personality, relationships, and role
- evidence: 1-3 short quotations or explicit textual facts supporting the identification
- voice_design_prompt: an OmniVoice voice parameter string using ONLY these tokens:
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

Sentences to process (JSON array with id and text):
{sentences_json}

For each sentence return:
- id: the sentence id (integer)
- character_id: the character id from the roster (use the narrator's id for narration; null if uncertain)
- tagged_text: the sentence text with optional non-verbal tags like [laughter], [sigh], [whisper], [shout], or null
  when no tag is needed (do not repeat unchanged text)
- confidence: a number from 0 to 1 for the speaker assignment
- reason: a brief evidence-based reason, such as an adjacent dialogue tag or turn-taking context

Also return chapter_summary: an updated spoiler-light summary incorporating this batch and the prior summary.
The roster descriptions are identity hints only and may be inaccurate. Ground the chapter summary exclusively in the
sentence text and prior chapter summary; never import plot events, body changes, relationships, or backstory from a
character description.
Return JSON with keys assignments and chapter_summary. No markdown or explanation.
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
                    "reason": {"type": "string"},
                },
                "required": ["id", "character_id", "tagged_text", "confidence", "reason"],
            },
        },
        "chapter_summary": {"type": "string"},
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
            "options": {"temperature": 0, "num_ctx": 32768, "num_predict": 4096},
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


def _extract_json(raw: str) -> Any:
    """Strip markdown code fences if present and parse JSON."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first and last fence lines
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(text)


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
                    "voice_design_prompt": profile.voice_design_prompt,
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
                "voice_design_prompt": c.get("voice_design_prompt"),
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
                        "voice_design_prompt": "[gender-male][pitch-medium][speed-normal]",
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
                "voice_design_prompt": "[gender-neutral][pitch-medium][speed-normal]",
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
                "voice_design_prompt": "[gender-neutral][pitch-medium][speed-normal]",
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
                    "voice_design_prompt": "[gender-female][pitch-medium][speed-normal]",
                    "is_narrator": False,
                },
                {
                    "name": "Minor Male Voice",
                    "aliases": ["Unnamed male speaker"],
                    "description": "Fallback voice for unnamed or one-scene male dialogue.",
                    "evidence": [],
                    "voice_design_prompt": "[gender-male][pitch-medium][speed-normal]",
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
                "voice_design_prompt": profile.voice_design_prompt,
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


async def diarize_sentences(book_id: int, db: AsyncSession) -> None:
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
    batch_size = 40
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
        if len(chapter_sentences) >= batch_size:
            story_started = True
        is_front_matter = (not story_started and len(chapter_sentences) < batch_size) or len(chapter_sentences) < 20
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
                    raise RuntimeError(f"LLM returned invalid JSON for diarization: {exc}\nRaw: {raw[:500]}") from exc

            if isinstance(batch_result, list):
                batch_result = {"assignments": batch_result, "chapter_summary": chapter.summary}
            if not isinstance(batch_result, dict) or not isinstance(batch_result.get("assignments"), list):
                raise RuntimeError(f"Expected a JSON object from diarization, got: {type(batch_result)}")
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

            chapter_summary = str(batch_result.get("chapter_summary") or chapter.summary or "")[:4000]
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
