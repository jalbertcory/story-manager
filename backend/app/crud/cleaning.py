"""Cleaning config CRUD operations."""

import re
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from .. import models, schemas


async def create_cleaning_config(db: AsyncSession, config: schemas.CleaningConfigCreate) -> models.CleaningConfig:
    db_config = models.CleaningConfig(**config.model_dump())
    db.add(db_config)
    await db.commit()
    await db.refresh(db_config)
    return db_config


async def get_cleaning_configs(db: AsyncSession) -> List[models.CleaningConfig]:
    result = await db.execute(select(models.CleaningConfig))
    return result.scalars().all()


async def get_matching_cleaning_config(db: AsyncSession, url: str) -> Optional[models.CleaningConfig]:
    result = await db.execute(select(models.CleaningConfig))
    configs = result.scalars().all()
    for cfg in configs:
        if re.search(cfg.url_pattern, url):
            return cfg
    return None


async def get_all_matching_cleaning_configs(db: AsyncSession, url: str) -> List[models.CleaningConfig]:
    result = await db.execute(select(models.CleaningConfig))
    return [cfg for cfg in result.scalars().all() if re.search(cfg.url_pattern, url)]


async def get_cleaning_config(db: AsyncSession, config_id: int) -> Optional[models.CleaningConfig]:
    result = await db.execute(select(models.CleaningConfig).filter(models.CleaningConfig.id == config_id))
    return result.scalars().first()


async def update_cleaning_config(
    db: AsyncSession, config: models.CleaningConfig, update: schemas.CleaningConfigUpdate
) -> models.CleaningConfig:
    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)
    await db.commit()
    await db.refresh(config)
    return config


async def delete_cleaning_config(db: AsyncSession, config: models.CleaningConfig) -> None:
    await db.delete(config)
    await db.commit()
