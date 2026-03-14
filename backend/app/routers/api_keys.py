"""Admin endpoints for managing reader API keys."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, schemas
from ..auth import generate_reader_token
from ..database import get_db

router = APIRouter()


@router.get("/api/reader-keys", response_model=list[schemas.ApiKey])
async def list_reader_keys(db: AsyncSession = Depends(get_db)) -> list[schemas.ApiKey]:
    return await crud.get_api_keys(db)


@router.post("/api/reader-keys", response_model=schemas.ApiKeyWithToken, status_code=status.HTTP_201_CREATED)
async def create_reader_key(
    request: schemas.ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
) -> schemas.ApiKeyWithToken:
    token, prefix = generate_reader_token()
    api_key = await crud.create_api_key(db, request.label, token, prefix)
    return schemas.ApiKeyWithToken(
        id=api_key.id,
        label=api_key.label,
        token_prefix=api_key.token_prefix,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        revoked_at=api_key.revoked_at,
        token=token,
    )


@router.delete("/api/reader-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_reader_key(key_id: int, db: AsyncSession = Depends(get_db)) -> None:
    revoked = await crud.revoke_api_key(db, key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Reader API key not found")
    return None
