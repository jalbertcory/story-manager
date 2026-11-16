"""Configure disposable file storage before conftest imports the application."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

# Services bind library paths at import time. An isolated database alone cannot
# protect real audio files when a test deletes a book with the same numeric ID.
_STORAGE = TemporaryDirectory(prefix="story-manager-tests-")
TEST_LIBRARY_PATH = Path(_STORAGE.name) / "library"
os.environ["STORY_MANAGER_LIBRARY_DIR"] = str(TEST_LIBRARY_PATH)
