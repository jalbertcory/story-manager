"""Validated metadata contracts, with room for provider and user JSON extensions."""

from collections.abc import Mapping
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, field_validator, with_config
from typing_extensions import TypedDict


class MetadataJobScope(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    book_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list)

    @field_validator("book_ids")
    @classmethod
    def unique_book_ids(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))


@with_config(ConfigDict(strict=True, extra="allow"))
class MetadataDetails(TypedDict, total=False):
    subtitle: str | None
    description: str | None
    publisher: str | None
    published_date: str | int | None
    language: str | None
    page_count: int | None
    cover_url: str | None
    series: str | None
    series_index: Annotated[float, Field(allow_inf_nan=False)] | None
    amazon_rating: Annotated[float, Field(allow_inf_nan=False)] | None
    amazon_review_count: int | None
    corroborating_sources: list[str] | None


@with_config(ConfigDict(strict=True, extra="allow"))
class RemoteIdentifiers(TypedDict, total=False):
    asin: str | None
    google_books_volume_id: str | None
    isbn_10: str | None
    isbn_13: str | None
    open_library_author_key: str | None
    open_library_edition_key: str | None
    open_library_work_key: str | None


METADATA_DETAILS = TypeAdapter(MetadataDetails)
REMOTE_IDENTIFIERS = TypeAdapter(RemoteIdentifiers)
JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def metadata_details(value: object) -> MetadataDetails:
    """Validate known fields and ensure extension fields are JSON too."""
    return METADATA_DETAILS.validate_python(JSON_OBJECT.validate_python(value, strict=True))


def metadata_json(value: Mapping[str, object]) -> dict[str, JsonValue]:
    return JSON_OBJECT.validate_python(value, strict=True)


def remote_identifiers(value: object) -> dict[str, JsonValue]:
    raw = JSON_OBJECT.validate_python(value, strict=True)
    REMOTE_IDENTIFIERS.validate_python(raw)
    return raw


def searchable_identifiers(value: object) -> dict[str, str]:
    """Legacy custom objects remain stored but are never mistaken for ISBNs/IDs."""
    if not isinstance(value, dict):
        return {}
    return {
        key: entry.strip() for key, entry in value.items() if isinstance(key, str) and isinstance(entry, str) and entry.strip()
    }
