"""Phases 2 & 3: LLM-based character roster generation and sentence diarization."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..models import AudiobookSettings

logger = logging.getLogger(__name__)

DEFAULT_ROSTER_PROMPT = """\
You are a literary analyst. Analyze the following text excerpt from a book and extract a list of all named \
characters (including the narrator if the text uses first person).

For each character produce:
- name: their name (use "Narrator" for first-person narrators)
- description: a 1-2 sentence description of their personality and role
- voice_design_prompt: an OmniVoice voice parameter string using ONLY these tokens:
  [gender-{male|female|neutral}] [pitch-{low|medium|high}] [speed-{slow|normal|fast}]
  Optional: [accent-{british|american|australian}] [age-{young|middle|old}]
  Example: [gender-male][pitch-low][speed-normal][age-middle]
- is_narrator: true only for the primary narrator

Return ONLY a valid JSON array of objects. No markdown, no explanation.

Text:
{text}
"""

DEFAULT_DIARIZATION_PROMPT = """\
You are a script editor. Assign each sentence to a speaker from the character roster and add non-verbal \
expression tags where appropriate.

Character roster (JSON):
{roster_json}

Previous context (last 5 sentences):
{context}

Sentences to process (JSON array with id and text):
{sentences_json}

For each sentence return:
- id: the sentence id (integer)
- character_id: the character id from the roster (use the narrator's id for narration; null if uncertain)
- tagged_text: the sentence text with optional non-verbal tags like [laughter], [sigh], [whisper], [shout]

Return ONLY a valid JSON array. No markdown, no explanation.
"""


async def _call_llm(settings: AudiobookSettings, messages: list[dict[str, Any]]) -> str:
    """Route to the configured LLM provider and return the text response."""
    if not settings.llm_api_key and not settings.llm_base_url:
        raise RuntimeError("LLM not configured: set llm_api_key or llm_base_url in Audio Settings.")

    provider = (settings.llm_provider or "openai").lower()
    model = settings.llm_model or "gpt-4o"

    headers = {"Content-Type": "application/json"}

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
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
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


async def generate_character_roster(book_id: int, db: AsyncSession) -> None:
    """Phase 2: extract characters from book text and persist to audiobook_characters."""
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None:
        raise RuntimeError("Audiobook settings not found.")

    chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    if not chapters:
        logger.warning("No chapters found for book %s during roster generation.", book_id)
        await crud.audiobook.set_book_pipeline_status(db, book_id, "diarizing")
        return

    # Collect text from up to 5 chapters (keeps prompt size manageable)
    text_chunks: list[str] = []
    for chapter in chapters[:5]:
        sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        text_chunks.append(" ".join(s.original_text for s in sentences))
    combined_text = "\n\n".join(text_chunks)[:12000]  # ~10k tokens safety cap

    prompt_template = settings.roster_prompt_template or DEFAULT_ROSTER_PROMPT
    prompt = prompt_template.format(text=combined_text)

    logger.info("Calling LLM for character roster (book %s).", book_id)
    raw = await _call_llm(settings, [{"role": "user", "content": prompt}])

    try:
        characters_data = _extract_json(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM returned invalid JSON for roster: {exc}\nRaw: {raw[:500]}") from exc

    if not isinstance(characters_data, list):
        raise RuntimeError(f"Expected a JSON array from LLM, got: {type(characters_data)}")

    # Normalise keys to match our model
    normalised: list[dict] = []
    for c in characters_data:
        normalised.append(
            {
                "name": str(c.get("name", "Unknown")),
                "description": c.get("description"),
                "voice_design_prompt": c.get("voice_design_prompt"),
                "is_narrator": bool(c.get("is_narrator", False)),
            }
        )

    await crud.audiobook.create_characters_bulk(db, book_id=book_id, characters_data=normalised)
    logger.info("Created %d characters for book %s.", len(normalised), book_id)
    await crud.audiobook.set_book_pipeline_status(db, book_id, "diarizing")


async def diarize_sentences(book_id: int, db: AsyncSession) -> None:
    """Phase 3: batch-assign speakers and expression tags to all pending sentences."""
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None:
        raise RuntimeError("Audiobook settings not found.")

    characters = await crud.audiobook.get_characters_for_book(db, book_id)
    roster_json = json.dumps(
        [
            {"id": c.id, "name": c.name, "description": c.description, "is_narrator": c.is_narrator}
            for c in characters
        ],
        ensure_ascii=False,
    )

    context_window: list[str] = []
    batch_size = 50

    while True:
        batch = await crud.audiobook.get_sentences_pending_diarization(db, book_id, limit=batch_size)
        if not batch:
            break

        sentences_json = json.dumps(
            [{"id": s.id, "text": s.original_text} for s in batch],
            ensure_ascii=False,
        )
        context_str = "\n".join(context_window[-5:]) if context_window else "(none)"

        prompt_template = settings.diarization_prompt_template or DEFAULT_DIARIZATION_PROMPT
        prompt = prompt_template.format(
            roster_json=roster_json,
            context=context_str,
            sentences_json=sentences_json,
        )

        logger.debug("Diarizing %d sentences for book %s.", len(batch), book_id)
        raw = await _call_llm(settings, [{"role": "user", "content": prompt}])

        try:
            results = _extract_json(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM returned invalid JSON for diarization: {exc}\nRaw: {raw[:500]}") from exc

        result_map = {r["id"]: r for r in results if isinstance(r, dict)}

        for sentence in batch:
            result = result_map.get(sentence.id, {})
            char_id = result.get("character_id")
            tagged = result.get("tagged_text") or sentence.original_text
            await crud.audiobook.update_sentence_diarization(db, sentence.id, char_id, tagged)
            context_window.append(sentence.original_text)

    logger.info("Diarization complete for book %s.", book_id)
    await crud.audiobook.set_book_pipeline_status(db, book_id, "audio_gen")
