"""Library-wide audiobook status overview."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..audiobook_schemas import AudiobookOverviewResponse
from ..database import get_db
from ..services.audiobook_status import audiobook_overview

router = APIRouter()


@router.get("/api/audiobooks/overview", response_model=AudiobookOverviewResponse)
async def get_audiobook_overview(db: AsyncSession = Depends(get_db)) -> AudiobookOverviewResponse:
    """Every book with human or AI audio, its sources' states, and the next step for each."""
    return await audiobook_overview(db)
