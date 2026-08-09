"""Structured, correlated, persistent, and redacted application logging."""

from __future__ import annotations

import collections
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .config import LOG_BACKUP_COUNT, LOG_DIR, LOG_MAX_BYTES
from .observability_context import job_id_var, request_id_var

_LOG_BUFFER: collections.deque = collections.deque(maxlen=1000)
_LOG_FILE = LOG_DIR / "story-manager.jsonl"

_REDACTION_PATTERNS = (
    (re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]+"), r"\1 [REDACTED]"),
    (
        re.compile(r"(?i)\b(authorization|cookie|set-cookie)\s*:\s*[^\r\n]+"),
        r"\1: [REDACTED]",
    ),
    (
        re.compile(
            r"""(?ix)(["']?(?:api[_-]?key|password|secret|token|session(?:_id)?|story_manager_admin)"""
            r"""["']?\s*[=:]\s*)["']?[^"',;\s}]+"""
        ),
        r"\1[REDACTED]",
    ),
    (re.compile(r"(?i)\b(postgres(?:ql)?(?:\+\w+)?://)[^@\s]+@"), r"\1[REDACTED]@"),
)


def redact_text(value: str) -> str:
    """Remove common credential forms from operator-visible diagnostics."""
    redacted = value
    for pattern, replacement in _REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_value(value: Any) -> Any:
    """Recursively redact mappings without changing their diagnostic shape."""
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if any(
                    marker in str(key).lower()
                    for marker in ("api_key", "authorization", "cookie", "password", "secret", "session", "token")
                )
                else redact_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


class _CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = request_id_var.get()
        if getattr(record, "job_id", None) is None:
            record.job_id = job_id_var.get()
        return True


def _record_entry(record: logging.LogRecord, formatter: logging.Formatter) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "message": redact_text(record.getMessage()),
    }
    if record.exc_info and record.exc_info[1]:
        entry["exception"] = redact_text(formatter.formatException(record.exc_info))
    if request_id := getattr(record, "request_id", None):
        entry["request_id"] = request_id
    if (job_id := getattr(record, "job_id", None)) is not None:
        entry["job_id"] = job_id
    return entry


class _StructuredFormatter(logging.Formatter):
    """JSON-lines formatter for both containers and persistent log files."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(_record_entry(record, self), default=str)


class _RedactedTextFormatter(logging.Formatter):
    """Apply the same credential redaction to human-readable console output."""

    def format(self, record: logging.LogRecord) -> str:
        original_message, original_args = record.msg, record.args
        try:
            record.msg = redact_text(record.getMessage())
            record.args = ()
            return super().format(record)
        finally:
            record.msg, record.args = original_message, original_args

    def formatException(self, exc_info) -> str:
        return redact_text(super().formatException(exc_info))


class _MemoryLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _LOG_BUFFER.append(_record_entry(record, self.formatter or logging.Formatter()))
        except Exception:
            self.handleError(record)


def setup_logging() -> tuple[logging.StreamHandler, _MemoryLogHandler, RotatingFileHandler]:
    use_json = os.getenv("LOG_FORMAT", "").lower() == "json"
    correlation_filter = _CorrelationFilter()
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.addFilter(correlation_filter)
    if use_json:
        console_handler.setFormatter(_StructuredFormatter())
    else:
        console_handler.setFormatter(
            _RedactedTextFormatter(
                "%(asctime)s %(levelname)s %(name)s " "[request_id=%(request_id)s job_id=%(job_id)s]: %(message)s"
            )
        )
    root_logger.addHandler(console_handler)

    mem_handler = _MemoryLogHandler()
    mem_handler.addFilter(correlation_filter)
    root_logger.addHandler(mem_handler)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.addFilter(correlation_filter)
    file_handler.setFormatter(_StructuredFormatter())
    root_logger.addHandler(file_handler)
    return console_handler, mem_handler, file_handler


def read_persisted_logs(*, limit: int = 500, level: str | None = None, log_file: Path | None = None) -> list[dict]:
    """Read the newest structured entries across the bounded rotated files."""
    target = log_file or _LOG_FILE
    candidates = [target.with_name(f"{target.name}.{index}") for index in range(LOG_BACKUP_COUNT, 0, -1)]
    candidates.append(target)
    entries: collections.deque = collections.deque(maxlen=max(1, limit))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            with candidate.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        entry = redact_value(json.loads(line))
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if level and entry.get("level") != level.upper():
                        continue
                    entries.append(entry)
        except OSError:
            continue
    if entries:
        return list(entries)
    memory = [redact_value(entry) for entry in _LOG_BUFFER]
    if level:
        memory = [entry for entry in memory if entry.get("level") == level.upper()]
    return memory[-limit:]
