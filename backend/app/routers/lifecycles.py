"""Read-only lifecycle vocabulary shared with the frontend."""

from fastapi import APIRouter

from ..lifecycle import lifecycle_manifest

router = APIRouter()


@router.get("/api/lifecycles")
async def get_lifecycle_definitions() -> dict:
    return lifecycle_manifest()
