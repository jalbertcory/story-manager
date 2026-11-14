"""Series gap and release tracking actions."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas
from ..database import get_db
from ..job_payloads import SeriesCheckPayload
from ..services.processing_queue import queue_processing_job
from ..services.series_tracking import dismiss_series_gaps, dismiss_series_release

router = APIRouter()


@router.post(
    "/api/series-tracking/check",
    response_model=schemas.ProcessingJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_series_check(db: AsyncSession = Depends(get_db)) -> schemas.ProcessingJob:
    job = await queue_processing_job(
        db=db,
        job_type="series_check",
        payload=SeriesCheckPayload(trigger="manual"),
        dedupe_key="series_check",
        progress_detail="Queued to check series gaps and releases",
    )
    return schemas.ProcessingJob.model_validate(job)


@router.post("/api/series-tracking/gaps/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_gaps(request: schemas.SeriesGapDismiss, db: AsyncSession = Depends(get_db)) -> None:
    await dismiss_series_gaps(db, request.series_name)
    return None


@router.post("/api/series-tracking/releases/{finding_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_release(finding_id: int, db: AsyncSession = Depends(get_db)) -> None:
    if not await dismiss_series_release(db, finding_id):
        raise HTTPException(status_code=404, detail="Series release not found")
    return None
