import os
from pathlib import Path

# Absolute path to backend/app/
APP_DIR = Path(__file__).parent.resolve()

# Absolute path to the library/ directory at the project root
LIBRARY_PATH = (APP_DIR / ".." / ".." / "library").resolve()

# Rename this marker whenever chapter concatenation semantics change. A
# missing marker makes existing packages resumable at assembly without a
# database migration or destructive audio regeneration.
AUDIOBOOK_ASSEMBLY_MARKER = ".epub3-overlay-v3"

GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")
