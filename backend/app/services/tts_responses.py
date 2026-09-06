"""Validate local TTS worker responses before the pipeline uses them."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Similarity = Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]
PositiveCount = Annotated[int, Field(gt=0)]
NonemptyText = Annotated[str, Field(min_length=1, pattern=r"\S")]


class TTSResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", hide_input_in_errors=True)


class DesignedVoiceResponse(TTSResponse):
    id: NonemptyText
    sample_text: NonemptyText
    sample_url: NonemptyText
    max_cross_voice_similarity: Similarity | None = None
    attempts: PositiveCount = 1


class BatchSpeechItem(TTSResponse):
    audio_base64: str
    duration_ms: PositiveCount
    voice_similarity: Similarity | None = None
    attempts: PositiveCount | None = None


class BatchSpeechResponse(TTSResponse):
    items: list[BatchSpeechItem]
