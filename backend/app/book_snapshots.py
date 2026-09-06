"""Validated book snapshots; omitted historical fields leave current values alone."""

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_serializer, field_validator


class BookSnapshot(BaseModel):
    # Unknown historical/future fields were never restored by this version.
    model_config = ConfigDict(strict=True, from_attributes=True, extra="ignore", revalidate_instances="always")
    title: str | None = None
    author: str | None = None
    series: str | None = None
    series_index: Decimal | None = Field(default=None, max_digits=6, decimal_places=2, allow_inf_nan=False)
    genre_tags: list[str] | None = None
    source_tags: list[str] | None = None
    user_genre_tags: list[str] | None = None
    metadata_remote_ids: dict[str, JsonValue] | None = None
    metadata_details: dict[str, JsonValue] | None = None
    metadata_sync_source: str | None = None
    metadata_synced_at: datetime | None = None
    notes: str | None = None
    removed_chapters: list[str] | None = None
    content_selectors: list[str] | None = None
    audiobook_enabled: bool = False

    @field_validator("series_index", mode="before")
    @classmethod
    def parse_series_index(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("series_index must be a number")
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        return value

    @field_validator("metadata_synced_at", mode="before")
    @classmethod
    def parse_timestamp(cls, value: object) -> object:
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    @field_serializer("series_index", when_used="json")
    def serialize_series_index(self, value: Decimal | None) -> float | None:
        return float(value) if value is not None else None
