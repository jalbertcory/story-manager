"""Typed, validated projections of the external metadata fields we consume.

Providers may add fields without breaking us. Invalid records are discarded
individually, so one malformed search hit does not hide the valid candidates.
"""

import logging
from typing import Annotated, TypeVar

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, with_config
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)
Number = Annotated[float, Field(allow_inf_nan=False)]
StringList = str | list[str] | None
SeriesIndex = Number | str | list[Number | str] | None


@with_config(ConfigDict(strict=True))
class OpenLibraryDoc(TypedDict, total=False):
    key: str | None
    title: str | None
    author_name: StringList
    author_key: StringList
    isbn: StringList
    cover_edition_key: str | None
    subject: list[str] | None
    series: StringList
    series_index: SeriesIndex
    cover_i: int | None
    publisher: StringList
    first_publish_year: int | None
    language: StringList
    number_of_pages_median: int | None


@with_config(ConfigDict(strict=True))
class TextValue(TypedDict, total=False):
    value: str


@with_config(ConfigDict(strict=True))
class OpenLibraryWork(TypedDict, total=False):
    key: str | None
    title: str | None
    subjects: list[str] | None
    series: StringList
    series_index: SeriesIndex
    covers: list[int] | None
    description: str | TextValue | None
    first_publish_date: str | None


@with_config(ConfigDict(strict=True))
class IndustryIdentifier(TypedDict, total=False):
    type: str | None
    identifier: str | None


@with_config(ConfigDict(strict=True))
class OrderNumber(TypedDict, total=False):
    number: Number | str | None
    value: Number | str | None


@with_config(ConfigDict(strict=True))
class VolumeSeries(TypedDict, total=False):
    orderNumber: Number | str | OrderNumber | None


@with_config(ConfigDict(strict=True))
class SeriesInfo(TypedDict, total=False):
    volumeSeries: list[VolumeSeries] | None
    bookDisplayNumber: Number | str | None
    shortSeriesBookTitle: str | None


@with_config(ConfigDict(strict=True))
class VolumeInfo(TypedDict, total=False):
    title: str | None
    subtitle: str | None
    authors: StringList
    industryIdentifiers: list[IndustryIdentifier] | None
    categories: StringList
    mainCategory: str | None
    imageLinks: dict[str, str | None] | None
    printedPageCount: int | None
    pageCount: int | None
    seriesInfo: SeriesInfo | None
    description: str | None
    publisher: str | None
    publishedDate: str | None
    language: str | None
    infoLink: str | None


@with_config(ConfigDict(strict=True))
class GoogleVolume(TypedDict, total=False):
    id: str | None
    volumeInfo: VolumeInfo | None


OPEN_LIBRARY_DOC = TypeAdapter(OpenLibraryDoc)
OPEN_LIBRARY_WORK = TypeAdapter(OpenLibraryWork)
GOOGLE_VOLUME = TypeAdapter(GoogleVolume)
_OBJECT = TypeAdapter(dict[str, object])
_ITEMS = TypeAdapter(list[object])
T = TypeVar("T")


def response_object(payload: object) -> dict[str, object]:
    try:
        return _OBJECT.validate_python(payload, strict=True)
    except ValidationError:
        logger.warning("Ignoring metadata response with a non-object envelope")
        return {}


def valid_record(payload: object, adapter: TypeAdapter[T]) -> T | None:
    try:
        return adapter.validate_python(payload)
    except ValidationError:
        logger.warning("Ignoring malformed metadata record (%s)", adapter)
        return None


def valid_records(payload: object, field: str, adapter: TypeAdapter[T]) -> list[T]:
    envelope = response_object(payload)
    try:
        items = _ITEMS.validate_python(envelope.get(field) or [], strict=True)
    except ValidationError:
        logger.warning("Ignoring metadata response with an invalid %s collection", field)
        return []
    return [record for item in items if (record := valid_record(item, adapter)) is not None]
