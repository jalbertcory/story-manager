"""Background metadata sync job orchestration and approval flows."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from .metadata_sync import (
    AUTO_APPROVE_THRESHOLD,
    PROPOSAL_THRESHOLD,
    MetadataSuggestion,
    apply_suggestion_to_book,
    generate_candidate_suggestions,
)

logger = logging.getLogger(__name__)

APPROVED_MATCH_STATUSES = {"approved", "auto_approved"}
MAX_MATCH_CANDIDATES = 5
AMBIGUOUS_MATCH_DELTA = 0.03


def _match_same_remote(match: models.BookMetadataMatch, suggestion: MetadataSuggestion) -> bool:
    return (match.remote_ids or {}) == (suggestion.remote_ids or {})


def _remote_signature_from_suggestion(suggestion: MetadataSuggestion) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, str(value)) for key, value in (suggestion.remote_ids or {}).items()))


async def create_metadata_sync_job_request(
    db: AsyncSession,
    *,
    trigger: str,
    book_ids: Optional[list[int]] = None,
) -> models.MetadataSyncJob:
    if book_ids:
        resolved_books = await crud.get_books_by_ids(db, book_ids)
    else:
        resolved_books = await crud.get_books(db, limit=100000)
    resolved_ids = [book.id for book in resolved_books]
    return await crud.create_metadata_sync_job(db, trigger=trigger, book_ids=resolved_ids)


async def queue_metadata_sync_job(
    db: AsyncSession,
    *,
    trigger: str,
    book_ids: Optional[list[int]] = None,
) -> models.MetadataSyncJob:
    from .metadata_sync_queue import get_metadata_sync_queue

    job = await create_metadata_sync_job_request(db, trigger=trigger, book_ids=book_ids)
    await get_metadata_sync_queue().enqueue(job.id)
    return job


def _upsert_match(
    existing_match: Optional[models.BookMetadataMatch],
    *,
    book_id: int,
    status: str,
    suggestion: Optional[MetadataSuggestion],
    checked_at: datetime,
    preserve_approval: bool = False,
) -> models.BookMetadataMatch:
    match = existing_match or models.BookMetadataMatch(book_id=book_id)
    match.status = status
    match.source = suggestion.source if suggestion and suggestion.matched else None
    match.match_confidence = Decimal(str(round(suggestion.match_confidence, 4))) if suggestion and suggestion.matched else None
    match.remote_title = suggestion.remote_title if suggestion and suggestion.matched else None
    match.remote_author = suggestion.remote_author if suggestion and suggestion.matched else None
    match.remote_url = suggestion.remote_url if suggestion and suggestion.matched else None
    match.remote_ids = suggestion.remote_ids if suggestion and suggestion.matched else None
    match.last_checked_at = checked_at
    if status in APPROVED_MATCH_STATUSES:
        match.approved_at = match.approved_at if preserve_approval else checked_at
        match.rejected_at = None
    elif status == "rejected":
        match.rejected_at = checked_at
    elif status == "pending":
        match.rejected_at = None
    elif status == "no_match":
        match.rejected_at = None
    return match


def _upsert_proposal(
    existing_proposal: Optional[models.MetadataProposal],
    *,
    book_id: int,
    match: Optional[models.BookMetadataMatch],
    suggestion: Optional[MetadataSuggestion],
    status: str,
    checked_at: datetime,
) -> models.MetadataProposal:
    proposal = existing_proposal or models.MetadataProposal(book_id=book_id)
    proposal.match_id = match.id if match and match.id else proposal.match_id
    proposal.status = status
    proposal.proposed_genre_tags = suggestion.new_genre_tags if suggestion else []
    proposal.possible_missing_series_books = suggestion.possible_missing_series_books if suggestion else []
    proposal.note = suggestion.note if suggestion else None
    if proposal.created_at is None:
        proposal.created_at = checked_at
    if status != "open":
        proposal.reviewed_at = checked_at
    return proposal


async def _sync_one_book(
    db: AsyncSession,
    *,
    book: models.Book,
    all_books: list[models.Book],
    checked_at: datetime,
) -> tuple[bool, bool, bool]:
    candidate_groups = await generate_candidate_suggestions([book], all_books, max_candidates=MAX_MATCH_CANDIDATES)
    suggestions = candidate_groups[0]
    suggestion = suggestions[0]

    existing_matches = await crud.get_metadata_matches_by_book_id(db, book.id)
    existing_match = existing_matches[0] if existing_matches else None
    existing_proposal = await crud.get_metadata_proposal_by_book_id(db, book.id)

    matched = suggestion.matched
    proposed = False
    applied = False

    if not matched:
        match = _upsert_match(existing_match, book_id=book.id, status="no_match", suggestion=None, checked_at=checked_at)
        if existing_match is None:
            db.add(match)
        if existing_proposal:
            existing_proposal.status = "resolved"
            existing_proposal.reviewed_at = checked_at
        await db.commit()
        return False, False, False

    has_close_alternative = any(
        candidate.matched
        and candidate.remote_ids != suggestion.remote_ids
        and candidate.match_confidence >= suggestion.match_confidence - AMBIGUOUS_MATCH_DELTA
        for candidate in suggestions[1:]
    )

    if existing_match and existing_match.status == "rejected" and _match_same_remote(existing_match, suggestion):
        match_status = "rejected"
    elif (
        existing_match and existing_match.status in APPROVED_MATCH_STATUSES and _match_same_remote(existing_match, suggestion)
    ):
        match_status = existing_match.status
    elif suggestion.match_confidence >= AUTO_APPROVE_THRESHOLD and not has_close_alternative:
        match_status = "auto_approved"
    elif suggestion.match_confidence >= PROPOSAL_THRESHOLD:
        match_status = "pending"
    else:
        match_status = "no_match"

    candidate_matches: list[models.BookMetadataMatch] = []
    if match_status in {"pending", *APPROVED_MATCH_STATUSES}:
        existing_by_signature = {
            tuple(sorted((key, str(value)) for key, value in (match.remote_ids or {}).items())): match
            for match in existing_matches
            if match.remote_ids
        }
        for index, candidate in enumerate(suggestions):
            if not candidate.matched:
                continue
            candidate_status = match_status if index == 0 else "pending"
            if candidate_status == "auto_approved" and index > 0:
                candidate_status = "pending"
            candidate_existing = existing_by_signature.get(_remote_signature_from_suggestion(candidate))
            if candidate_existing and candidate_existing.status in {"approved", "auto_approved", "rejected"}:
                candidate_status = candidate_existing.status
            candidate_match = _upsert_match(
                candidate_existing,
                book_id=book.id,
                status=candidate_status,
                suggestion=candidate,
                checked_at=checked_at,
                preserve_approval=bool(candidate_existing and candidate_existing.status in APPROVED_MATCH_STATUSES),
            )
            if candidate_existing is None:
                db.add(candidate_match)
                await db.flush()
            candidate_matches.append(candidate_match)

    match = (
        candidate_matches[0]
        if candidate_matches
        else _upsert_match(
            existing_match,
            book_id=book.id,
            status=match_status,
            suggestion=suggestion if match_status != "no_match" else None,
            checked_at=checked_at,
            preserve_approval=bool(existing_match and existing_match.status in APPROVED_MATCH_STATUSES),
        )
    )
    if not candidate_matches and existing_match is None:
        db.add(match)
        await db.flush()

    if match_status in APPROVED_MATCH_STATUSES:
        applied = apply_suggestion_to_book(book, suggestion, source=suggestion.source, synced_at=checked_at)
        if suggestion.possible_missing_series_books:
            proposal = _upsert_proposal(
                existing_proposal,
                book_id=book.id,
                match=match,
                suggestion=suggestion,
                status="open",
                checked_at=checked_at,
            )
            proposal.proposed_genre_tags = []
            if existing_proposal is None:
                db.add(proposal)
            proposed = True
        elif existing_proposal:
            existing_proposal.status = "resolved"
            existing_proposal.reviewed_at = checked_at
    elif match_status == "pending":
        proposal = _upsert_proposal(
            existing_proposal,
            book_id=book.id,
            match=match,
            suggestion=suggestion,
            status="open",
            checked_at=checked_at,
        )
        if existing_proposal is None:
            db.add(proposal)
        proposed = True
    else:
        if existing_proposal:
            existing_proposal.status = "resolved"
            existing_proposal.reviewed_at = checked_at

    await db.commit()
    return True, proposed, applied


async def process_metadata_sync_job(db: AsyncSession, job_id: int) -> None:
    job = await crud.get_metadata_sync_job(db, job_id)
    if job is None:
        logger.warning("Metadata sync job %s no longer exists.", job_id)
        return

    await crud.mark_metadata_sync_job_running(db, job)

    try:
        scope = job.scope or {}
        book_ids = scope.get("book_ids") or []
        target_books = await crud.get_books_by_ids(db, book_ids)
        all_books = await crud.get_books(db, limit=100000)
        checked_at = datetime.now(timezone.utc)

        for book in target_books:
            matched, proposed, applied = await _sync_one_book(db, book=book, all_books=all_books, checked_at=checked_at)
            job = await crud.get_metadata_sync_job(db, job_id)
            if job is None:
                return
            await crud.mark_metadata_sync_job_progress(
                db,
                job,
                processed_increment=1,
                matched_increment=1 if matched else 0,
                proposed_increment=1 if proposed else 0,
                applied_increment=1 if applied else 0,
            )

        job = await crud.get_metadata_sync_job(db, job_id)
        if job is not None:
            await crud.complete_metadata_sync_job(db, job)
    except Exception as exc:
        logger.exception("Metadata sync job %s failed.", job_id)
        job = await crud.get_metadata_sync_job(db, job_id)
        if job is not None:
            await crud.fail_metadata_sync_job(db, job, str(exc))


async def queue_stale_metadata_sync(db: AsyncSession, *, stale_after_days: int) -> Optional[models.MetadataSyncJob]:
    stale_books = await crud.get_stale_books_for_metadata_sync(db, stale_after_days=stale_after_days)
    if not stale_books:
        return None
    return await queue_metadata_sync_job(
        db,
        trigger="stale_recheck",
        book_ids=[book.id for book in stale_books],
    )


async def approve_metadata_match(
    db: AsyncSession,
    match_id: int,
) -> tuple[models.BookMetadataMatch, Optional[models.MetadataProposal]]:
    match = await crud.get_metadata_match(db, match_id)
    if match is None:
        raise ValueError("Metadata match not found")

    book = await crud.get_book(db, match.book_id)
    if book is None:
        raise ValueError("Book not found")

    proposal = await crud.get_metadata_proposal_by_book_id(db, book.id)
    if proposal is None:
        raise ValueError("Metadata proposal not found")

    match.status = "approved"
    match.approved_at = datetime.now(timezone.utc)
    match.rejected_at = None

    genre_tags = proposal.proposed_genre_tags or []
    merged_genres = sorted({*(book.genre_tags or []), *genre_tags}, key=str.casefold)
    book.genre_tags = merged_genres
    book.metadata_remote_ids = {
        **(book.metadata_remote_ids or {}),
        **(match.remote_ids or {}),
    }
    book.metadata_sync_source = match.source or "open_library"
    book.metadata_synced_at = datetime.now(timezone.utc)

    if proposal.possible_missing_series_books:
        proposal.proposed_genre_tags = []
    else:
        proposal.status = "resolved"
        proposal.reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(match)
    if proposal is not None:
        await db.refresh(proposal)
    return match, proposal


async def reject_metadata_match(
    db: AsyncSession,
    match_id: int,
) -> tuple[models.BookMetadataMatch, Optional[models.MetadataProposal]]:
    match = await crud.get_metadata_match(db, match_id)
    if match is None:
        raise ValueError("Metadata match not found")

    proposal = await crud.get_metadata_proposal_by_book_id(db, match.book_id)
    match.status = "rejected"
    match.rejected_at = datetime.now(timezone.utc)
    if proposal is not None:
        remaining_matches = [
            candidate
            for candidate in await crud.get_metadata_matches_by_book_id(db, match.book_id)
            if candidate.id != match.id and candidate.status == "pending"
        ]
        if remaining_matches:
            proposal.status = "open"
            if proposal.match_id == match.id:
                proposal.match_id = remaining_matches[0].id
        else:
            proposal.status = "dismissed"
            proposal.reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(match)
    if proposal is not None:
        await db.refresh(proposal)
    return match, proposal


async def dismiss_metadata_proposal(db: AsyncSession, proposal_id: int) -> models.MetadataProposal:
    proposal = await crud.get_metadata_proposal(db, proposal_id)
    if proposal is None:
        raise ValueError("Metadata proposal not found")
    proposal.status = "dismissed"
    proposal.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(proposal)
    return proposal


def build_metadata_proposal_summary(
    proposal: models.MetadataProposal,
    book: models.Book,
    match: Optional[models.BookMetadataMatch],
    *,
    candidate_matches: Optional[list[models.BookMetadataMatch]] = None,
) -> schemas.MetadataProposalSummary:
    candidates = candidate_matches or ([match] if match is not None else [])
    return schemas.MetadataProposalSummary(
        id=proposal.id,
        book_id=book.id,
        book_title=book.title,
        book_author=book.author,
        book_series=book.series,
        match=schemas.MetadataMatch.model_validate(match) if match is not None else None,
        candidate_matches=[schemas.MetadataMatch.model_validate(candidate) for candidate in candidates],
        proposed_genre_tags=list(proposal.proposed_genre_tags or []),
        possible_missing_series_books=list(proposal.possible_missing_series_books or []),
        note=proposal.note,
        status=proposal.status,
        created_at=proposal.created_at,
        reviewed_at=proposal.reviewed_at,
    )
