"""Unified processing-job API used by the Processing page and action feedback."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, schemas
from ..database import get_db
from ..services.processing_queue import queue_processing_job

router = APIRouter()


def _response(job, book_title: str | None = None) -> schemas.ProcessingJob:
    return schemas.ProcessingJob.model_validate(job).model_copy(update={"book_title": book_title})


@router.get("/api/processing/jobs", response_model=list[schemas.ProcessingJob])
async def list_processing_jobs(
    statuses: str | None = Query(None, description="Comma-separated statuses"),
    job_type: str | None = None,
    book_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[schemas.ProcessingJob]:
    selected_statuses = [item.strip() for item in statuses.split(",") if item.strip()] if statuses else None
    rows = await crud.get_processing_jobs(
        db,
        statuses=selected_statuses,
        job_type=job_type,
        book_id=book_id,
        limit=limit,
    )
    return [_response(job, book_title) for job, book_title in rows]


@router.get("/api/processing/jobs/{job_id}", response_model=schemas.ProcessingJob)
async def get_processing_job(job_id: int, db: AsyncSession = Depends(get_db)) -> schemas.ProcessingJob:
    job = await crud.get_processing_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    book_title = None
    if job.book_id is not None:
        book = await crud.get_book(db, job.book_id)
        book_title = book.title if book else None
    return _response(job, book_title)


@router.post(
    "/api/processing/jobs",
    response_model=schemas.ProcessingJobsCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_processing_jobs(
    body: schemas.ProcessingJobRequest,
    db: AsyncSession = Depends(get_db),
) -> schemas.ProcessingJobsCreated:
    jobs = []
    if body.job_type in {"clean_all", "refresh_all"}:
        jobs.append(
            await queue_processing_job(
                db=db,
                job_type=body.job_type,
                payload=body.payload,
                dedupe_key=body.job_type,
            )
        )
    elif body.job_type in {"clean_book", "refresh_book", "audiobook_pipeline", "retry_cover"}:
        if not body.book_ids:
            raise HTTPException(status_code=422, detail="Select at least one book")
        books = await crud.get_books_by_ids(db, body.book_ids)
        found_ids = {book.id for book in books}
        missing_ids = sorted(set(body.book_ids) - found_ids)
        if missing_ids:
            raise HTTPException(status_code=404, detail=f"Books not found: {missing_ids}")
        for book in books:
            payload = body.payload or {}
            mode = payload.get("mode", "reconcile")
            if body.job_type == "refresh_book" and (book.source_type != "web" or not book.source_url):
                raise HTTPException(status_code=422, detail=f"Book {book.id} is not a refreshable web book")
            if body.job_type == "audiobook_pipeline" and not book.audiobook_enabled:
                raise HTTPException(status_code=422, detail=f"AI audiobook generation is not enabled for book {book.id}")
            if body.job_type == "retry_cover" and not book.immutable_path:
                raise HTTPException(status_code=422, detail=f"Book {book.id} has no EPUB to extract a cover from")
            if body.job_type == "audiobook_pipeline":
                dedupe_key = f"audiobook_pipeline:book:{book.id}:v{book.content_version or 1}" + (
                    f":{mode}" if mode != "reconcile" else ""
                )
            else:
                dedupe_key = f"{body.job_type}:book:{book.id}"
            jobs.append(
                await queue_processing_job(
                    db=db,
                    job_type=body.job_type,
                    book_id=book.id,
                    target_type="book",
                    target_id=book.id,
                    target_content_version=book.content_version,
                    payload=payload,
                    dedupe_key=dedupe_key,
                )
            )
    else:
        if body.target_id is None:
            raise HTTPException(status_code=422, detail="This job type requires target_id")
        jobs.append(
            await queue_processing_job(
                db=db,
                job_type=body.job_type,
                target_id=body.target_id,
                payload=body.payload,
                dedupe_key=f"{body.job_type}:target:{body.target_id}",
            )
        )
    return schemas.ProcessingJobsCreated(jobs=[_response(job) for job in jobs])


@router.post("/api/processing/jobs/{job_id}/retry", response_model=schemas.ProcessingJob)
async def retry_processing_job(job_id: int, db: AsyncSession = Depends(get_db)) -> schemas.ProcessingJob:
    job = await crud.retry_processing_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=409, detail="Only failed or canceled jobs can be retried")
    return _response(job)


@router.delete("/api/processing/jobs/{job_id}", response_model=schemas.ProcessingJob)
async def cancel_processing_job(job_id: int, db: AsyncSession = Depends(get_db)) -> schemas.ProcessingJob:
    job = await crud.request_processing_job_cancel(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return _response(job)
