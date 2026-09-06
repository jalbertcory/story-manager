"""Validate transcription and ffprobe JSON before media processing uses it."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
    model_validator,
)


def _numeric_time(value: object) -> object:
    # ffprobe emits seconds as decimal strings, whereas ASR emits JSON numbers.
    if isinstance(value, str):
        return float(value)
    return value


# Keep converted milliseconds within the exact integer range used by JSON clients.
Seconds = Annotated[float, Field(ge=0, le=9_007_199_254_740, allow_inf_nan=False)]
ProbeSeconds = Annotated[Seconds, BeforeValidator(_numeric_time)]


class MediaResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", hide_input_in_errors=True)


class TranscriptionWordResponse(MediaResponse):
    word: str
    start: Seconds
    end: Seconds
    score: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.end < self.start:
            raise ValueError("Word end precedes its start")
        return self


class TranscriptionResponse(MediaResponse):
    language: str | None = None
    duration: Seconds | None = None
    words: list[TranscriptionWordResponse]


class TranscriptionHealth(MediaResponse):
    model_config = ConfigDict(strict=True, extra="allow", hide_input_in_errors=True)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    status: str
    model: str | None = None
    device: str | None = None
    compute_type: str | None = None
    batch_size: int | None = Field(default=None, gt=0)
    default_language: str | None = None


class ProbeFormat(MediaResponse):
    duration: ProbeSeconds | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class ProbeChapter(MediaResponse):
    start_time: ProbeSeconds
    end_time: ProbeSeconds
    tags: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.end_time <= self.start_time:
            raise ValueError("Chapter end must follow its start")
        return self


class ProbeDisposition(MediaResponse):
    attached_pic: int = Field(default=0, ge=0, le=1)


class ProbeStream(MediaResponse):
    index: int = Field(ge=0)
    disposition: ProbeDisposition = Field(default_factory=ProbeDisposition)
    tags: dict[str, str] = Field(default_factory=dict)


class AudioProbe(MediaResponse):
    format: ProbeFormat = Field(default_factory=ProbeFormat)
    chapters: list[ProbeChapter] = Field(default_factory=list)
    streams: list[ProbeStream] = Field(default_factory=list)

    @field_validator("chapters", mode="before")
    @classmethod
    def usable_chapters(cls, value: object) -> object:
        # Chapter tables are optional metadata. A broken entry must not prevent
        # importing playable audio; absent usable chapters fall back to one track.
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        chapters = []
        for entry in value:
            try:
                chapters.append(ProbeChapter.model_validate(entry))
            except ValidationError:
                continue
        return chapters
