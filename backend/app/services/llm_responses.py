"""Validate model-generated content before it influences persisted data."""

from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from typing_extensions import NotRequired, TypedDict

Confidence = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Expression = Literal["laughter", "sigh", "whisper", "surprise-oh", "dissatisfaction-hnn", "confirmation-en"]


class LLMResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", hide_input_in_errors=True)


class RosterCharacter(LLMResponse):
    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    evidence: list[str] = Field(default_factory=list)
    voice_prompt: str | None = None
    is_narrator: bool = False


class RosterResponse(LLMResponse):
    book_summary: str | None = None
    characters: list[RosterCharacter] = Field(min_length=1)


class ChapterSummaryResponse(LLMResponse):
    summary: str


class DiarizationAssignment(LLMResponse):
    id: int = Field(validation_alias=AliasChoices("id", "i"))
    character_id: int | None = Field(default=None, validation_alias=AliasChoices("character_id", "c"))
    expression: Expression | None = Field(default=None, validation_alias=AliasChoices("expression", "e"))
    tagged_text: str | None = None
    confidence: Confidence = 0.9
    reason: str | None = None


class AssignmentData(TypedDict):
    id: int
    character_id: int | None
    expression: NotRequired[Expression | None]
    tagged_text: NotRequired[str | None]
    confidence: float
    reason: str | None
    _fallback: NotRequired[bool]


class DiarizationData(TypedDict):
    assignments: list[AssignmentData]
    chapter_summary: str | None


class DiarizationEnvelope(LLMResponse):
    # Validate assignments individually so valid rows survive a partial response.
    assignments: list[object]
    chapter_summary: str | None = None


class ArbitrationResponse(LLMResponse):
    selected_index: int = Field(ge=-1)
    exact_match: bool
    confidence: Confidence
    reason: str = Field(max_length=500)


class SearchRefinementResponse(LLMResponse):
    title: str = Field(max_length=300)
    author: str = Field(max_length=200)
    confidence: Confidence
    reason: str = Field(max_length=500)


class IdentityResponse(SearchRefinementResponse):
    series: str = Field(default="", max_length=200)
    series_index: float = Field(default=0, allow_inf_nan=False)
    isbn_10: str = Field(default="", max_length=32)
    isbn_13: str = Field(default="", max_length=32)


class TextMessage(LLMResponse):
    content: str


class OllamaResponse(LLMResponse):
    message: TextMessage


class OllamaStreamEvent(LLMResponse):
    message: TextMessage | None = None
    done: bool = False


class ChatChoice(LLMResponse):
    message: TextMessage


class ChatResponse(LLMResponse):
    choices: list[ChatChoice] = Field(min_length=1)


class ContentBlock(LLMResponse):
    type: str = "text"
    text: str | None = None


class AnthropicResponse(LLMResponse):
    content: list[ContentBlock] = Field(min_length=1)

    def text_content(self) -> str:
        text = "".join(block.text for block in self.content if block.type == "text" and block.text is not None)
        if not text:
            raise ValueError("LLM returned no text content")
        return text
