import collections
import json
import logging
import os
import sys
from datetime import datetime, timezone

# In-memory log buffer (most-recent 1000 records)
_LOG_BUFFER: collections.deque = collections.deque(maxlen=1000)


class _StructuredFormatter(logging.Formatter):
    """JSON-lines formatter for structured logging in container environments."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Include request_id if attached to the log record
        request_id = getattr(record, "request_id", None)
        if request_id:
            log_entry["request_id"] = request_id
        return json.dumps(log_entry, default=str)


class _MemoryLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.format(record),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            entry["request_id"] = request_id
        _LOG_BUFFER.append(entry)


def setup_logging() -> _MemoryLogHandler:
    use_json = os.getenv("LOG_FORMAT", "").lower() == "json"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    if use_json:
        console_handler.setFormatter(_StructuredFormatter())
    else:
        console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root_logger.addHandler(console_handler)

    # Memory handler (always uses plain message format for the API endpoint)
    mem_handler = _MemoryLogHandler()
    mem_handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(mem_handler)
    return mem_handler
