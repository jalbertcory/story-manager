"""EPUB and ZIP upload routes and duplicate detection."""

from pathlib import Path

import pytest

from api_harness import client, create_dummy_epub, create_zip_archive


@pytest.mark.asyncio
async def test_upload_epub(db_session):
    """
    Test uploading an EPUB file.
    """
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    epub_filename = "Uploaded Book.epub"
    epub_filepath = library_path / epub_filename
    author_dir = library_path / "Uploader"
    stored_filename = "Uploaded Book - Uploader.epub"
    immutable_filepath = author_dir / f"immutable_{stored_filename}"
    current_filepath = author_dir / stored_filename

    # Create a dummy epub file
    create_dummy_epub(epub_filepath, "Uploaded Book", "Uploader", "Upload Series")

    with open(epub_filepath, "rb") as f:
        response = client.post("/api/books/upload_epub", files={"file": (epub_filename, f, "application/epub+zip")})

    # Clean up the dummy files
    epub_filepath.unlink()
    immutable_filepath.unlink()
    current_filepath.unlink()
    author_dir.rmdir()

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Uploaded Book"
    assert data["author"] == "Uploader"
    assert data["series"] == "Upload Series"
    assert data["immutable_path"] == str(Path("library") / "Uploader" / f"immutable_{stored_filename}")
    assert data["current_path"] == str(Path("library") / "Uploader" / stored_filename)
    assert data["master_word_count"] > 0
    assert data["current_word_count"] == data["master_word_count"]

    # Verify that the book was added to the database
    response = client.get("/api/books")
    assert response.status_code == 200
    books = response.json()
    assert len(books) == 1
    assert books[0]["title"] == "Uploaded Book"


@pytest.mark.asyncio
async def test_upload_zip_with_nested_epubs(db_session):
    """
    Test uploading a ZIP file with EPUBs in nested folders ignores non-EPUB files.
    """
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)

    first_epub = library_path / "Nested One.epub"
    second_epub = library_path / "Nested Two.epub"
    zip_path = library_path / "batch-upload.zip"

    create_dummy_epub(first_epub, "Nested One", "Author One")
    create_dummy_epub(second_epub, "Nested Two", "Author Two")

    create_zip_archive(
        zip_path,
        {
            "collection/one/Nested One.epub": first_epub.read_bytes(),
            "collection/two/Nested Two.epub": second_epub.read_bytes(),
            "collection/notes/readme.txt": b"ignore me",
        },
    )

    with open(zip_path, "rb") as f:
        response = client.post("/api/books/upload_epubs", files=[("files", ("batch-upload.zip", f, "application/zip"))])

    first_epub.unlink(missing_ok=True)
    second_epub.unlink(missing_ok=True)
    zip_path.unlink(missing_ok=True)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {item["status"] for item in data} == {"success"}
    assert {item["book"]["title"] for item in data} == {"Nested One", "Nested Two"}
    assert all(item["filename"].startswith("batch-upload.zip:collection/") for item in data)

    # Imported books are written into author folders named by title and author from epub metadata.
    for expected_path in [
        library_path / "Author One" / "Nested One - Author One.epub",
        library_path / "Author One" / "immutable_Nested One - Author One.epub",
        library_path / "Author Two" / "Nested Two - Author Two.epub",
        library_path / "Author Two" / "immutable_Nested Two - Author Two.epub",
    ]:
        assert expected_path.exists()
        expected_path.unlink(missing_ok=True)
    (library_path / "Author One").rmdir()
    (library_path / "Author Two").rmdir()


@pytest.mark.asyncio
async def test_upload_zip_with_no_epubs(db_session):
    """
    Test uploading a ZIP file with no EPUB entries reports a skipped result.
    """
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    zip_path = library_path / "non-books.zip"
    create_zip_archive(zip_path, {"nested/readme.txt": b"hello", "nested/image.jpg": b"jpg"})

    with open(zip_path, "rb") as f:
        response = client.post("/api/books/upload_epubs", files=[("files", ("non-books.zip", f, "application/zip"))])

    zip_path.unlink(missing_ok=True)

    assert response.status_code == 200
    assert response.json() == [
        {
            "filename": "non-books.zip",
            "status": "skipped",
            "book": None,
            "error": "No EPUB files found in ZIP archive",
        }
    ]


@pytest.mark.asyncio
async def test_duplicate_epub_upload(db_session):
    """
    Test that uploading an EPUB with the same title and author as an existing book returns 409.
    """
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    epub_filename = "Dup Book.epub"
    epub_filepath = library_path / epub_filename
    immutable_filepath = library_path / f"immutable_{epub_filename}"

    create_dummy_epub(epub_filepath, "Dup Book", "Dup Author")

    # First upload — should succeed
    with open(epub_filepath, "rb") as f:
        response = client.post("/api/books/upload_epub", files={"file": (epub_filename, f, "application/epub+zip")})
    assert response.status_code == 201

    # Recreate the file for the second upload (first upload consumed the stream)
    create_dummy_epub(epub_filepath, "Dup Book", "Dup Author")

    # Second upload — same title + author → 409
    with open(epub_filepath, "rb") as f:
        response = client.post("/api/books/upload_epub", files={"file": (epub_filename, f, "application/epub+zip")})
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]

    # Clean up
    for p in [epub_filepath, immutable_filepath]:
        if p.exists():
            p.unlink()


@pytest.mark.asyncio
async def test_epub_upload_deduplicates_matching_epub_source(db_session):
    """Two epub uploads with the same full title and author are blocked → 409."""
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    title = "The Lighthouse at the Edge of Everything"
    author = "Cordelia Vance-Whitmore"
    epub_filename = "lighthouse-edge.epub"
    epub_filepath = library_path / epub_filename

    create_dummy_epub(epub_filepath, title, author)
    with open(epub_filepath, "rb") as f:
        first = client.post("/api/books/upload_epub", files={"file": (epub_filename, f, "application/epub+zip")})
    assert first.status_code == 201

    create_dummy_epub(epub_filepath, title, author)
    with open(epub_filepath, "rb") as f:
        second = client.post("/api/books/upload_epub", files={"file": (epub_filename, f, "application/epub+zip")})
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"]

    epub_filepath.unlink(missing_ok=True)
