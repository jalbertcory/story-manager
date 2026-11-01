"""Audiobook API: aggregates the import, pipeline, character and settings routers."""

from fastapi import APIRouter

from . import audiobook_characters, audiobook_imports, audiobook_pipeline, audiobook_settings

router = APIRouter()
router.include_router(audiobook_imports.router)
router.include_router(audiobook_pipeline.router)
router.include_router(audiobook_characters.router)
router.include_router(audiobook_settings.router)
