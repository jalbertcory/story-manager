"""Use the configured LLM only to resolve deterministic metadata ties."""

from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..metadata_sync import MetadataSuggestion
    from .evidence import SearchIdentity

from ...models import AudiobookSettings, Book
from ..audiobook_llm import _call_llm
from ..endpoint_pool import configured_endpoints

logger = logging.getLogger(__name__)

ARBITRATION_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_index": {"type": "integer", "minimum": -1},
        "exact_match": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "maxLength": 500},
    },
    "required": ["selected_index", "exact_match", "confidence", "reason"],
    "additionalProperties": False,
}

SEARCH_REFINEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "maxLength": 300},
        "author": {"type": "string", "maxLength": 200},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "maxLength": 500},
    },
    "required": ["title", "author", "confidence", "reason"],
    "additionalProperties": False,
}


def _llm_available(settings: AudiobookSettings | None) -> bool:
    for endpoint in configured_endpoints(settings, "llm"):
        provider = str(endpoint.get("provider") or "").casefold()
        if provider == "ollama":
            return True
        if provider not in {"", "none", "stub"} and (endpoint.get("api_key") or endpoint.get("base_url")):
            return True
    return False


def _needs_arbitration(candidates: list[MetadataSuggestion]) -> bool:
    matched = [candidate for candidate in candidates if candidate.matched]
    if not matched:
        return False
    top = matched[0]
    if top.match_issues:
        return True
    if top.match_confidence < 0.92:
        return top.match_confidence >= 0.72
    if len(matched) < 2:
        return False
    return matched[1].match_confidence >= top.match_confidence - 0.06


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {}


async def refine_unmatched_search_identity(
    identity: SearchIdentity, settings: AudiobookSettings | None
) -> dict[str, Any] | None:
    """Derive one conservative retry query when all provider searches failed."""

    if settings is None or not _llm_available(settings) or identity.used_llm or not identity.opening_excerpt:
        return None
    prompt = f"""The initial Google Books and Open Library searches returned no plausible candidate. Derive the exact
published title and primary author for one retry from explicit title-page, copyright, and ISBN context. Remove filename,
series-order, format, and collection decorations from the title. Do not invent or translate names. Return confidence below
0.9 when the opening evidence is not explicit.

Initial title: {identity.title}
Initial author: {identity.author}
Opening-page evidence:
{identity.opening_excerpt}
"""
    try:
        raw = await _call_llm(
            settings,
            [
                {
                    "role": "system",
                    "content": "You derive conservative bibliographic search queries. Return only the requested JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            response_schema=SEARCH_REFINEMENT_SCHEMA,
        )
        refined = _parse_json(raw)
    except Exception:
        logger.warning("LLM unmatched-book query refinement failed.", exc_info=True)
        return None
    title = str(refined.get("title") or "").strip()
    author = str(refined.get("author") or "").strip()
    confidence = float(refined.get("confidence") or 0)
    if confidence < 0.9 or not title or not author:
        return None
    if title.casefold() == identity.title.casefold() and author.casefold() == identity.author.casefold():
        return None
    return {"title": title, "author": author, "reason": str(refined.get("reason") or "").strip()}


async def arbitrate_candidate_suggestions(
    book: Book,
    identity: SearchIdentity,
    candidates: list[MetadataSuggestion],
    settings: AudiobookSettings | None,
) -> list[MetadataSuggestion]:
    """Re-rank a close candidate set without overriding hard contradictions."""

    if settings is None or not _llm_available(settings) or not _needs_arbitration(candidates):
        return candidates

    candidate_payload = [
        {
            "index": index,
            "provider": candidate.source,
            "title": candidate.remote_title,
            "author": candidate.remote_author,
            "series": (candidate.metadata_details or {}).get("series"),
            "series_index": (candidate.metadata_details or {}).get("series_index"),
            "identifiers": candidate.remote_ids or {},
            "deterministic_score": round(candidate.match_confidence, 4),
            "hard_issues": candidate.match_issues or [],
        }
        for index, candidate in enumerate(candidates)
        if candidate.matched
    ]
    local_identity = {
        "title": identity.title,
        "author": identity.author,
        "series": identity.series,
        "series_index": identity.series_index,
        "identifiers": identity.remote_ids,
    }
    prompt = f"""Choose the exact bibliographic record for this local ebook. Do not choose a summary, omnibus, boxed set,
study guide, or a different volume. Series position and ISBN evidence are decisive. A hard issue must not be ignored.
Return selected_index -1 if none is an exact match.

Local identity:
    {json.dumps(local_identity, ensure_ascii=False)}

Opening-page evidence (may be empty or contain advertisements; use only explicit bibliographic statements):
{identity.opening_excerpt}

Candidates:
{json.dumps(candidate_payload, ensure_ascii=False)}
"""
    try:
        raw = await _call_llm(
            settings,
            [
                {
                    "role": "system",
                    "content": "You are a conservative bibliographic resolver. Return only the requested JSON object.",
                },
                {"role": "user", "content": prompt},
            ],
            response_schema=ARBITRATION_SCHEMA,
        )
        decision = _parse_json(raw)
    except Exception:
        logger.warning("LLM metadata arbitration failed for book %s; keeping deterministic ranking.", book.id, exc_info=True)
        return candidates

    selected_index = int(decision.get("selected_index", -1))
    confidence = float(decision.get("confidence") or 0)
    exact_match = bool(decision.get("exact_match"))
    reason = str(decision.get("reason") or "").strip()
    selected_payload = next((candidate for candidate in candidate_payload if candidate["index"] == selected_index), None)
    if selected_payload is None:
        if confidence >= 0.9 and candidates:
            issue = f"LLM could not verify an exact candidate{f': {reason}' if reason else '.'}"
            candidates[0].match_issues = list(dict.fromkeys([*(candidates[0].match_issues or []), issue]))
            candidates[0].match_confidence = min(candidates[0].match_confidence, 0.89)
        return candidates

    selected = candidates[selected_index]
    if not exact_match or confidence < 0.9:
        return candidates

    if reason:
        selected.note = f"LLM candidate verification: {reason}" + (f" {selected.note}" if selected.note else "")
    if not selected.match_issues and selected.match_confidence >= 0.75:
        # Opening-page evidence is required before the LLM may turn a review
        # candidate into an unattended match. Without it, it only breaks ties.
        ceiling = 0.99 if identity.opening_excerpt and confidence >= 0.94 else 0.96 if identity.opening_excerpt else 0.91
        selected.match_confidence = max(selected.match_confidence, ceiling)

    reordered = [selected, *(candidate for candidate in candidates if candidate is not selected)]
    return reordered
