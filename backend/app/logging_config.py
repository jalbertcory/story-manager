import collections
import logging
from datetime import datetime, timezone

# In-memory log buffer (most-recent 1000 records)
_LOG_BUFFER: collections.deque = collections.deque(maxlen=1000)


class _MemoryLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _LOG_BUFFER.append(
            {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
            }
        )


def setup_logging() -> _MemoryLogHandler:
    logging.basicConfig(level=logging.INFO)
    mem_handler = _MemoryLogHandler()
    mem_handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(mem_handler)
    return mem_handler
