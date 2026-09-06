"""Use the configured LLM only to resolve deterministic metadata ties."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..metadata_sync import MetadataSuggestion
    from .evidence import SearchIdentity

from ...models import AudiobookSettings, Book
from ..audiobook_llm import _call_llm, _extract_json
from ..llm_responses import ArbitrationResponse, SearchRefinementResponse
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
        provider = str(endpoint.provider or "").casefold()
        if provider == "ollama":
            return True
        if provider not in {"", "none", "stub"} and (endpoint.api_key or endpoint.base_url):
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


async def refine_unmatched_search_identity(
    identity: SearchIdentity, settings: AudiobookSettings | None
) -> SearchRefinementResponse | None:
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
        refined = SearchRefinementResponse.model_validate(_extract_json(raw))
    except Exception:
        logger.warning("LLM unmatched-book query refinement failed.", exc_info=True)
        return None
    title = refined.title.strip()
    author = refined.author.strip()
    confidence = refined.confidence
    if confidence < 0.9 or not title or not author:
        return None
    if title.casefold() == identity.title.casefold() and author.casefold() == identity.author.casefold():
        return None
    return SearchRefinementResponse(title=title, author=author, reason=refined.reason.strip(), confidence=confidence)


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
        decision = ArbitrationResponse.model_validate(_extract_json(raw))
        if decision.selected_index >= len(candidates) or (
            decision.selected_index >= 0 and not candidates[decision.selected_index].matched
        ):
            raise ValueError("LLM selected an index outside the candidate set")
    except Exception:
        logger.warning("LLM metadata arbitration failed for book %s; keeping deterministic ranking.", book.id, exc_info=True)
        return candidates

    selected_index = decision.selected_index
    confidence = decision.confidence
    exact_match = decision.exact_match
    reason = decision.reason.strip()
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
