"""Read-only lifecycle vocabulary shared with the frontend."""

from collections.abc import Mapping

from fastapi import APIRouter

from ..lifecycle import lifecycle_manifest

router = APIRouter()


@router.get("/api/lifecycles", response_model=dict)
async def get_lifecycle_definitions() -> Mapping[str, Mapping[str, object]]:
    return lifecycle_manifest()
