"""Story recaps: read what is written and queue the LLM to write more."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..crud.processing import ACTIVE_PROCESSING_STATUSES
from ..database import get_db
from ..job_payloads import StoryRecapPayload
from ..lifecycle import ProcessingJobStatus
from ..services import story_recap
from ..services.processing_queue import queue_processing_job

router = APIRouter()


async def _book_or_404(db: AsyncSession, book_id: int) -> models.Book:
    book = await crud.get_book(db, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


async def _entry(db: AsyncSession, book: models.Book, kind: story_recap.RecapKind) -> schemas.StoryRecapEntry:
    state = await story_recap.recap_state(db, book, kind)
    return schemas.StoryRecapEntry(
        kind=kind,
        recap=state.recap.recap if state.recap else None,
        stale=state.stale,
        updated_at=(state.recap.updated_at or state.recap.created_at) if state.recap else None,
        llm_model=state.recap.llm_model if state.recap else None,
        covered_books=[
            schemas.StoryRecapBook(
                id=covered.id,
                title=covered.title or "Untitled",
                series_index=float(covered.series_index) if covered.series_index is not None else None,
            )
            for covered in state.covered_books
        ],
    )


@router.get("/api/books/{book_id}/recap", response_model=schemas.StoryRecapResponse)
async def get_story_recap(book_id: int, db: AsyncSession = Depends(get_db)) -> schemas.StoryRecapResponse:
    book = await _book_or_404(db, book_id)
    settings = await crud.audiobook.get_audiobook_settings(db)
    jobs = [job for job, _title in await crud.get_processing_jobs(db, job_type="story_recap", book_id=book_id, limit=20)]
    active = next((job for job in jobs if job.status in ACTIVE_PROCESSING_STATUSES), None)
    latest = max(jobs, key=lambda job: job.id, default=None)
    failed = latest is not None and latest.status == ProcessingJobStatus.ERROR.value
    return schemas.StoryRecapResponse(
        book_id=book.id,
        series=book.series,
        llm_configured=story_recap.llm_configured(settings),
        book=await _entry(db, book, "book"),
        story_so_far=await _entry(db, book, "story_so_far"),
        active_job=schemas.ProcessingJob.model_validate(active) if active else None,
        last_error=latest.error if failed and latest is not None else None,
    )


@router.post(
    "/api/books/{book_id}/recap",
    response_model=schemas.ProcessingJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_story_recap(
    book_id: int, request: schemas.StoryRecapRequest, db: AsyncSession = Depends(get_db)
) -> schemas.ProcessingJob:
    book = await _book_or_404(db, book_id)
    settings = await crud.audiobook.get_audiobook_settings(db)
    if not story_recap.llm_configured(settings):
        raise HTTPException(status_code=409, detail="Set up a language model under Audio & AI Configuration first.")
    if request.kind == "story_so_far" and not await story_recap.series_predecessors(db, book):
        raise HTTPException(status_code=409, detail="There are no earlier books in this series to recap.")
    if request.kind == "book" and not book.current_path:
        raise HTTPException(status_code=409, detail="This book has no readable text to recap.")
    job = await queue_processing_job(
        db=db,
        job_type="story_recap",
        book_id=book.id,
        payload=StoryRecapPayload(kind=request.kind, force=request.force),
        dedupe_key=f"story_recap:{book.id}:{request.kind}",
        progress_detail="Queued to write the recap",
    )
    return schemas.ProcessingJob.model_validate(job)
