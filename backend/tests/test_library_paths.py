"""Every audiobook writer and reader resolves per-book files under one directory."""

from __future__ import annotations

from backend.app.services import audiobook_import, audiobook_tts, library_paths


def test_audiobook_files_share_one_per_book_directory(tmp_path, monkeypatch):
    # A library root not named "library" used to split generated snippets
    # (LIBRARY_PATH.parent / "library") from imports (LIBRARY_PATH).
    library = tmp_path / "custom-library-root"
    monkeypatch.setattr(library_paths, "LIBRARY_PATH", library)

    book_dir = library_paths.book_audiobook_dir(7)

    assert book_dir == library / "audiobooks" / "7"
    assert library_paths.audiobooks_root() == library / "audiobooks"
    assert audiobook_tts._snippet_path(7, 3).parent.parent == book_dir
    assert audiobook_import.imported_audiobook_dir(7, 2).parent.parent == book_dir
