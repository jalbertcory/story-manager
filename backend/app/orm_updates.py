"""Validate partial updates before assigning explicitly typed ORM fields."""

from collections.abc import Mapping
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
from . import models, schemas
from .endpoint_types import EndpointConfig


class UpdateModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True, revalidate_instances="always")


class SettingsPatch(UpdateModel):
    llm_provider: str | None = None
    llm_api_key: str | None = Field(default=None, repr=False)
    llm_base_url: str | None = None
    llm_model: str | None = None
    tts_provider: str | None = None
    tts_api_key: str | None = Field(default=None, repr=False)
    tts_base_url: str | None = None
    tts_model: str | None = None
    tts_default_voice: str | None = None
    tts_max_block_chars: int = 500
    tts_voice_similarity_threshold: float = 0.45
    tts_quality_attempts: int = 3
    transcription_provider: str | None = None
    transcription_api_key: str | None = Field(default=None, repr=False)
    transcription_base_url: str | None = None
    transcription_model: str | None = None
    transcription_language: str | None = None
    llm_endpoints: list[EndpointConfig] | None = None
    tts_endpoints: list[EndpointConfig] | None = None
    transcription_endpoints: list[EndpointConfig] | None = None
    roster_prompt_template: str | None = None
    diarization_prompt_template: str | None = None


class CharacterPatch(UpdateModel):
    name: str = ""
    description: str | None = None
    voice_prompt: str | None = None
    tts_voice_id: str | None = None
    tts_voice_provider: str | None = None
    tts_seed: int | None = None
    is_narrator: bool = False


def apply_settings_patch(record: models.AudiobookSettings, data: Mapping[str, object] | SettingsPatch) -> None:
    patch = SettingsPatch.model_validate(data)
    if "llm_provider" in patch.model_fields_set:
        record.llm_provider = patch.llm_provider
    if "llm_api_key" in patch.model_fields_set:
        record.llm_api_key = patch.llm_api_key
    if "llm_base_url" in patch.model_fields_set:
        record.llm_base_url = patch.llm_base_url
    if "llm_model" in patch.model_fields_set:
        record.llm_model = patch.llm_model
    if "tts_provider" in patch.model_fields_set:
        record.tts_provider = patch.tts_provider
    if "tts_api_key" in patch.model_fields_set:
        record.tts_api_key = patch.tts_api_key
    if "tts_base_url" in patch.model_fields_set:
        record.tts_base_url = patch.tts_base_url
    if "tts_model" in patch.model_fields_set:
        record.tts_model = patch.tts_model
    if "tts_default_voice" in patch.model_fields_set:
        record.tts_default_voice = patch.tts_default_voice
    if "tts_max_block_chars" in patch.model_fields_set:
        record.tts_max_block_chars = patch.tts_max_block_chars
    if "tts_voice_similarity_threshold" in patch.model_fields_set:
        record.tts_voice_similarity_threshold = patch.tts_voice_similarity_threshold
    if "tts_quality_attempts" in patch.model_fields_set:
        record.tts_quality_attempts = patch.tts_quality_attempts
    if "transcription_provider" in patch.model_fields_set:
        record.transcription_provider = patch.transcription_provider
    if "transcription_api_key" in patch.model_fields_set:
        record.transcription_api_key = patch.transcription_api_key
    if "transcription_base_url" in patch.model_fields_set:
        record.transcription_base_url = patch.transcription_base_url
    if "transcription_model" in patch.model_fields_set:
        record.transcription_model = patch.transcription_model
    if "transcription_language" in patch.model_fields_set:
        record.transcription_language = patch.transcription_language
    if "llm_endpoints" in patch.model_fields_set:
        record.llm_endpoints = (
            [endpoint.model_dump(mode="json") for endpoint in patch.llm_endpoints] if patch.llm_endpoints is not None else None
        )
    if "tts_endpoints" in patch.model_fields_set:
        record.tts_endpoints = (
            [endpoint.model_dump(mode="json") for endpoint in patch.tts_endpoints] if patch.tts_endpoints is not None else None
        )
    if "transcription_endpoints" in patch.model_fields_set:
        record.transcription_endpoints = (
            [endpoint.model_dump(mode="json") for endpoint in patch.transcription_endpoints]
            if patch.transcription_endpoints is not None
            else None
        )
    if "roster_prompt_template" in patch.model_fields_set:
        record.roster_prompt_template = patch.roster_prompt_template
    if "diarization_prompt_template" in patch.model_fields_set:
        record.diarization_prompt_template = patch.diarization_prompt_template


def apply_character_patch(record: models.AudiobookCharacter, data: Mapping[str, object] | CharacterPatch) -> None:
    patch = CharacterPatch.model_validate(data)
    if "name" in patch.model_fields_set:
        record.name = patch.name
    if "description" in patch.model_fields_set:
        record.description = patch.description
    if "voice_prompt" in patch.model_fields_set:
        record.voice_prompt = patch.voice_prompt
    if "tts_voice_id" in patch.model_fields_set:
        record.tts_voice_id = patch.tts_voice_id
    if "tts_voice_provider" in patch.model_fields_set:
        record.tts_voice_provider = patch.tts_voice_provider
    if "tts_seed" in patch.model_fields_set:
        record.tts_seed = patch.tts_seed
    if "is_narrator" in patch.model_fields_set:
        record.is_narrator = patch.is_narrator


def apply_book_patch(book: models.Book, patch: schemas.BookUpdate) -> None:
    if "audiobook_enabled" in patch.model_fields_set and patch.audiobook_enabled is None:
        raise ValueError("audiobook_enabled cannot be null")
    if "title" in patch.model_fields_set:
        book.title = patch.title
    if "author" in patch.model_fields_set:
        book.author = patch.author
    if "series" in patch.model_fields_set:
        book.series = patch.series
    if "series_index" in patch.model_fields_set:
        book.series_index = Decimal(str(patch.series_index)) if patch.series_index is not None else None
    if "genre_tags" in patch.model_fields_set:
        book.genre_tags = patch.genre_tags
    if "user_genre_tags" in patch.model_fields_set:
        book.user_genre_tags = patch.user_genre_tags
    if "source_tags" in patch.model_fields_set:
        book.source_tags = patch.source_tags
    if "metadata_remote_ids" in patch.model_fields_set:
        book.metadata_remote_ids = patch.metadata_remote_ids
    if patch.audiobook_enabled is not None:
        book.audiobook_enabled = patch.audiobook_enabled
    if "removed_chapters" in patch.model_fields_set:
        book.removed_chapters = patch.removed_chapters
    if "content_selectors" in patch.model_fields_set:
        book.content_selectors = patch.content_selectors
    if "notes" in patch.model_fields_set:
        book.notes = patch.notes
    if "series" in patch.model_fields_set and not patch.series:
        book.series_index = None


def apply_cleaning_patch(config: models.CleaningConfig, patch: schemas.CleaningConfigUpdate) -> None:
    if ("name" in patch.model_fields_set and patch.name is None) or (
        "url_pattern" in patch.model_fields_set and patch.url_pattern is None
    ):
        raise ValueError("Cleaning config name and url_pattern cannot be null")
    if patch.name is not None:
        config.name = patch.name
    if patch.url_pattern is not None:
        config.url_pattern = patch.url_pattern
    if "chapter_selectors" in patch.model_fields_set:
        config.chapter_selectors = patch.chapter_selectors
    if "content_selectors" in patch.model_fields_set:
        config.content_selectors = patch.content_selectors
