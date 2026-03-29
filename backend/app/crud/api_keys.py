"""API key CRUD operations."""

from typing import List
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from .. import models
from ..auth import hash_token


async def create_api_key(db: AsyncSession, label: str, token: str, prefix: str) -> models.ApiKey:
    api_key = models.ApiKey(label=label, token_prefix=prefix, token_hash=hash_token(token))
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return api_key


async def get_api_keys(db: AsyncSession) -> List[models.ApiKey]:
    result = await db.execute(select(models.ApiKey).order_by(models.ApiKey.created_at.desc()))
    return result.scalars().all()


async def revoke_api_key(db: AsyncSession, key_id: int) -> bool:
    api_key = await db.get(models.ApiKey, key_id)
    if api_key is None:
        return False
    if api_key.revoked_at is None:
        api_key.revoked_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(api_key)
    return True
