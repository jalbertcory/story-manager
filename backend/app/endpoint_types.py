"""Validated endpoint configuration used across routing, persistence and metrics."""

from datetime import datetime
from typing import Optional
from pydantic import ConfigDict, Field, field_validator
from .api_model import APIModel as BaseModel


class EndpointConfig(BaseModel):
    # Older records can contain extra fields; validate the fields we consume.
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    id: str = ""
    name: str = ""
    provider: str = ""
    api_key: str | None = Field(default=None, repr=False)
    base_url: str | None = None
    model: str | None = None
    default_voice: str | None = None
    language: str | None = None

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return value.strip().lower()


class EndpointUpdate(EndpointConfig):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    provider: str


class EndpointSpeedBuckets(BaseModel):
    under_5s: int
    from_5s_to_15s: int
    from_15s_to_60s: int
    over_60s: int


class EndpointStats(BaseModel):
    endpoint_id: str
    name: str
    provider: str
    model: Optional[str]
    requests: int
    answered: int
    failed: int
    success_rate: Optional[float]
    average_ms: Optional[float]
    p50_ms: Optional[float]
    p95_ms: Optional[float]
    fastest_ms: Optional[float]
    slowest_ms: Optional[float]
    answered_24h: int
    average_24h_ms: Optional[float]
    speed_buckets: EndpointSpeedBuckets
    last_answered_at: Optional[datetime]
