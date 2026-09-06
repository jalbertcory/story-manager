"""Shared structured-log contract, independent of application initialization."""

from typing_extensions import TypedDict, NotRequired
from pydantic import ConfigDict, with_config


@with_config(ConfigDict(strict=True))
class LogEntry(TypedDict):
    timestamp: str
    level: str
    logger: str
    message: str
    exception: NotRequired[str]
    request_id: NotRequired[str]
    job_id: NotRequired[int]
