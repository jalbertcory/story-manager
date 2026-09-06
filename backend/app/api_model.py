"""Pydantic models expose fields always emitted by response serialization."""

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
