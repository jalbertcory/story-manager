"""Tests for upload validation: magic bytes, size limits, zip safety."""

import io
import zipfile

import pytest
from fastapi import HTTPException

from backend.app.upload_validation import (
    MAX_IMAGE_BYTES,
    MAX_UPLOAD_BYTES,
    MAX_ZIP_ENTRIES,
    validate_image_upload,
    validate_magic_bytes,
    validate_file_size,
    validate_upload,
    validate_zip_safety,
)


def _make_zip(entries: dict[str, bytes] = None) -> bytes:
    """Create a valid ZIP in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in (entries or {"test.txt": b"hello"}).items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestValidateMagicBytes:
    def test_valid_zip(self):
        payload = _make_zip()
        validate_magic_bytes(payload, "test.zip")  # should not raise

    def test_empty_file(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_magic_bytes(b"", "empty.epub")
        assert exc_info.value.status_code == 400
        assert "empty" in exc_info.value.detail

    def test_invalid_magic_bytes(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_magic_bytes(b"not a zip file contents", "bad.epub")
        assert exc_info.value.status_code == 400
        assert "not a valid EPUB or ZIP" in exc_info.value.detail

    def test_pdf_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_magic_bytes(b"%PDF-1.4 ...", "document.epub")
        assert exc_info.value.status_code == 400


class TestValidateFileSize:
    def test_within_limit(self):
        validate_file_size(b"x" * 100, "small.epub")  # should not raise

    def test_exceeds_limit(self):
        # We can't allocate 500MB in tests, so we monkey-patch conceptually.
        # Instead, test with a payload larger than MAX_UPLOAD_BYTES.
        # Use a small fake to test the logic by checking the threshold.
        # Just verify the boundary condition with a smaller payload.
        payload = b"x" * (MAX_UPLOAD_BYTES + 1)
        with pytest.raises(HTTPException) as exc_info:
            validate_file_size(payload, "huge.epub")
        assert exc_info.value.status_code == 413
        assert "exceeding" in exc_info.value.detail

    def test_exactly_at_limit(self):
        payload = b"x" * MAX_UPLOAD_BYTES
        validate_file_size(payload, "exact.epub")  # should not raise


class TestValidateZipSafety:
    def test_valid_zip(self):
        payload = _make_zip({"file.txt": b"content"})
        validate_zip_safety(payload, "valid.zip")  # should not raise

    def test_bad_zip(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_zip_safety(b"PK\x03\x04corrupted", "bad.zip")
        assert exc_info.value.status_code == 400
        assert "not a valid ZIP" in exc_info.value.detail

    def test_path_traversal_absolute(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("/etc/passwd", b"root:x:0:0")
        with pytest.raises(HTTPException) as exc_info:
            validate_zip_safety(buf.getvalue(), "traversal.zip")
        assert exc_info.value.status_code == 400
        assert "unsafe path" in exc_info.value.detail

    def test_path_traversal_dotdot(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../../etc/passwd", b"root:x:0:0")
        with pytest.raises(HTTPException) as exc_info:
            validate_zip_safety(buf.getvalue(), "traversal2.zip")
        assert exc_info.value.status_code == 400
        assert "unsafe path" in exc_info.value.detail

    def test_too_many_entries(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i in range(MAX_ZIP_ENTRIES + 1):
                zf.writestr(f"file_{i}.txt", b"x")
        with pytest.raises(HTTPException) as exc_info:
            validate_zip_safety(buf.getvalue(), "toomany.zip")
        assert exc_info.value.status_code == 400
        assert "entry limit" in exc_info.value.detail


class TestValidateUpload:
    def test_valid_epub_like_zip(self):
        payload = _make_zip({"mimetype": b"application/epub+zip", "content.opf": b"<opf/>"})
        validate_upload(payload, "book.epub")  # should not raise

    def test_rejects_non_zip(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_upload(b"plain text file", "notabook.epub")
        assert exc_info.value.status_code == 400


class TestValidateImageUpload:
    def test_valid_jpeg(self):
        # JPEG magic bytes + some padding
        payload = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        validate_image_upload(payload, "cover.jpg")  # should not raise

    def test_valid_png(self):
        payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        validate_image_upload(payload, "cover.png")  # should not raise

    def test_empty_image(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_image_upload(b"", "empty.jpg")
        assert exc_info.value.status_code == 400

    def test_invalid_format(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_image_upload(b"not an image at all", "fake.jpg")
        assert exc_info.value.status_code == 400
        assert "not a recognized image" in exc_info.value.detail

    def test_oversized_image(self):
        payload = b"\xff\xd8\xff\xe0" + b"\x00" * (MAX_IMAGE_BYTES + 1)
        with pytest.raises(HTTPException) as exc_info:
            validate_image_upload(payload, "huge.jpg")
        assert exc_info.value.status_code == 413
