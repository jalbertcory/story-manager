import os
from pathlib import Path

# Absolute path to backend/app/
APP_DIR = Path(__file__).parent.resolve()

# Absolute path to the library/ directory at the project root
LIBRARY_PATH = (APP_DIR / ".." / ".." / "library").resolve()

# Application logs survive ordinary restarts and rotate in a bounded directory.
LOG_DIR = Path(os.getenv("STORY_MANAGER_LOG_DIR", str(LIBRARY_PATH.parent / "logs"))).resolve()
LOG_MAX_BYTES = max(64 * 1024, int(os.getenv("STORY_MANAGER_LOG_MAX_BYTES", str(5 * 1024 * 1024))))
LOG_BACKUP_COUNT = max(1, int(os.getenv("STORY_MANAGER_LOG_BACKUP_COUNT", "3")))

# Rename this marker whenever chapter concatenation semantics change. A
# missing marker makes existing packages resumable at assembly without a
# database migration or destructive audio regeneration.
AUDIOBOOK_ASSEMBLY_MARKER = ".epub3-overlay-v3"

GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")

# Deleted books remain restorable for this many days. Operators can override
# the window without changing existing recycle-bin deadlines.
RECYCLE_BIN_RETENTION_DAYS = max(1, int(os.getenv("RECYCLE_BIN_RETENTION_DAYS", "30")))
