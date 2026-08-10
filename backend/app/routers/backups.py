"""Backup creation, inventory, verification, download, and deletion API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas
from ..config import BACKUP_PATH, BACKUP_RETENTION_COUNT
from ..database import get_db
from ..services.backups import BackupError, list_backups, resolve_backup
from ..services.processing_queue import queue_processing_job

router = APIRouter()


def _job_response(job) -> schemas.ProcessingJob:
    return schemas.ProcessingJob.model_validate(job)


@router.get("/api/backups", response_model=schemas.BackupInventory)
async def get_backups() -> dict[str, object]:
    return {"retention_count": BACKUP_RETENTION_COUNT, "backups": list_backups(BACKUP_PATH)}


@router.post("/api/backups", response_model=schemas.ProcessingJob, status_code=status.HTTP_202_ACCEPTED)
async def create_backup(db: AsyncSession = Depends(get_db)) -> schemas.ProcessingJob:
    job = await queue_processing_job(
        db=db,
        job_type="create_backup",
        dedupe_key="create_backup",
        progress_detail="Queued to create a verified backup",
    )
    return _job_response(job)


@router.post(
    "/api/backups/{filename}/verify",
    response_model=schemas.ProcessingJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def verify_backup(filename: str, db: AsyncSession = Depends(get_db)) -> schemas.ProcessingJob:
    try:
        resolve_backup(BACKUP_PATH, filename)
    except BackupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    job = await queue_processing_job(
        db=db,
        job_type="verify_backup",
        payload={"filename": filename},
        dedupe_key=f"verify_backup:{filename}",
        progress_detail=f"Queued to verify {filename}",
    )
    return _job_response(job)


@router.get("/api/backups/{filename}/download")
async def download_backup(filename: str) -> FileResponse:
    try:
        archive = resolve_backup(BACKUP_PATH, filename)
    except BackupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        archive,
        filename=archive.name,
        media_type="application/zip",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.delete("/api/backups/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(filename: str) -> Response:
    try:
        archive = resolve_backup(BACKUP_PATH, filename)
    except BackupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    archive.unlink()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
