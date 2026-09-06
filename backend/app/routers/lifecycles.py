"""Read-only lifecycle vocabulary shared with the frontend."""

from .. import api_schemas as contracts
from collections.abc import Mapping

from fastapi import APIRouter

from ..lifecycle import lifecycle_manifest

router = APIRouter()


@router.get("/api/lifecycles", response_model=dict[str, contracts.LifecycleDefinition])
async def get_lifecycle_definitions() -> Mapping[str, Mapping[str, object]]:
    return lifecycle_manifest()
