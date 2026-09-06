"""Narrow interfaces for the untyped FanFicFare update API.

The tuple layout and adapter attributes follow epubutils.get_update_data and
BaseSiteAdapter. Opaque per-adapter chapter metadata is retained on round trips.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol, TypeAlias
from typing_extensions import NotRequired, TypedDict

from bs4 import Tag


class EpubMetadata(TypedDict):
    title: str
    author: str
    series: str | None
    genre_tags: NotRequired[list[str]]
    source_tags: NotRequired[list[str]]


class ChapterRecord(TypedDict):
    url: str
    title: NotRequired[str]


OldImages: TypeAlias = dict[str, tuple[str, bytes]]
OldCover: TypeAlias = tuple[str, str, bytes, str, str, bytes] | None
ChapterMetadata: TypeAlias = Mapping[str | None, Mapping[str, object]]
UpdateData: TypeAlias = tuple[
    str | None, int, list[Tag], OldImages, OldCover, bytes | None, str | None, dict[str, Tag], ChapterMetadata
]


class ChapterNormalizer(Protocol):
    def normalize_chapterurl(self, url: str) -> str: ...


class Story(Protocol):
    def setMetadata(self, key: str, value: int) -> None: ...


class UpdateAdapter(ChapterNormalizer, Protocol):
    chapterUrls: list[ChapterRecord]
    story: Story
    oldchapters: list[Tag]
    oldimgs: OldImages
    oldcover: OldCover
    calibrebookmark: bytes | None
    logfile: str | None
    oldchaptersmap: dict[str, Tag]
    oldchaptersdata: ChapterMetadata

    def setChaptersRange(self, first: str | None, last: str | None) -> None: ...
    def getStoryMetadataOnly(self) -> object: ...
    def get_chapters(self) -> Sequence[Mapping[str, object]]: ...


class Configuration(Protocol):
    def set(self, section: str, key: str, value: str) -> None: ...


class Writer(Protocol):
    def writeStory(self) -> None: ...
