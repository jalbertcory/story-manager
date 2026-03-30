"""Metadata sync endpoints for background jobs, match approval, and proposals."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from .. import crud, schemas
from ..services.metadata_jobs import (
    approve_metadata_match,
    build_metadata_proposal_summary,
    dismiss_metadata_proposal,
    queue_metadata_sync_job,
    reject_metadata_match,
)
from ..services.metadata_sync import apply_metadata_sync, preview_metadata_sync

router = APIRouter()


@router.post("/api/metadata/jobs", response_model=schemas.MetadataSyncJob)
async def create_metadata_job(
    body: schemas.MetadataJobRequest,
    db: AsyncSession = Depends(get_db),
) -> schemas.MetadataSyncJob:
    job = await queue_metadata_sync_job(db, trigger=body.trigger, book_ids=body.book_ids)
    return schemas.MetadataSyncJob.model_validate(job)


@router.get("/api/metadata/jobs/latest", response_model=schemas.MetadataSyncJob | None)
async def get_latest_metadata_job(
    db: AsyncSession = Depends(get_db),
) -> schemas.MetadataSyncJob | None:
    job = await crud.get_latest_metadata_sync_job(db)
    return schemas.MetadataSyncJob.model_validate(job) if job is not None else None


@router.get("/api/metadata/inbox", response_model=list[schemas.MetadataProposalSummary])
async def get_metadata_inbox(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> list[schemas.MetadataProposalSummary]:
    rows = await crud.get_metadata_inbox_entries(db, limit=limit)
    return [build_metadata_proposal_summary(proposal, book, match) for proposal, book, match in rows]


@router.post("/api/metadata/matches/{match_id}/approve", response_model=schemas.MetadataMatch)
async def approve_match(
    match_id: int,
    db: AsyncSession = Depends(get_db),
) -> schemas.MetadataMatch:
    try:
        match, _proposal = await approve_metadata_match(db, match_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return schemas.MetadataMatch.model_validate(match)


@router.post("/api/metadata/matches/{match_id}/reject", response_model=schemas.MetadataMatch)
async def reject_match(
    match_id: int,
    db: AsyncSession = Depends(get_db),
) -> schemas.MetadataMatch:
    try:
        match, _proposal = await reject_metadata_match(db, match_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return schemas.MetadataMatch.model_validate(match)


@router.post("/api/metadata/proposals/{proposal_id}/dismiss", response_model=schemas.MetadataProposalSummary)
async def dismiss_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
) -> schemas.MetadataProposalSummary:
    try:
        proposal = await dismiss_metadata_proposal(db, proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    book = await crud.get_book(db, proposal.book_id)
    match = await crud.get_metadata_match_by_book_id(db, proposal.book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return build_metadata_proposal_summary(proposal, book, match)


@router.post("/api/metadata/sync-preview", response_model=schemas.MetadataSyncPreviewResponse)
async def sync_metadata_preview(
    body: schemas.MetadataSyncPreviewRequest,
    db: AsyncSession = Depends(get_db),
) -> schemas.MetadataSyncPreviewResponse:
    return await preview_metadata_sync(db, book_ids=body.book_ids)


@router.post("/api/metadata/apply", response_model=schemas.MetadataSyncApplyResponse)
async def sync_metadata_apply(
    body: schemas.MetadataSyncApplyRequest,
    db: AsyncSession = Depends(get_db),
) -> schemas.MetadataSyncApplyResponse:
    return await apply_metadata_sync(db, book_ids=body.book_ids)
