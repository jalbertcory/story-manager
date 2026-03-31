import os
from pathlib import Path

# Absolute path to backend/app/
APP_DIR = Path(__file__).parent.resolve()

# Absolute path to the library/ directory at the project root
LIBRARY_PATH = (APP_DIR / ".." / ".." / "library").resolve()

GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")
