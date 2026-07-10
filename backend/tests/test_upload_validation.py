"""Tests for upload validation: magic bytes, size limits, zip safety."""

import io
import zipfile

import pytest
from fastapi import HTTPException

from backend.app.upload_validation import (
    MAX_IMAGE_BYTES,
    MAX_ZIP_ENTRIES,
    detect_image_extension,
    read_upload_limited,
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

    def test_exceeds_limit(self, monkeypatch):
        monkeypatch.setattr("backend.app.upload_validation.MAX_UPLOAD_BYTES", 16)
        payload = b"x" * 17
        with pytest.raises(HTTPException) as exc_info:
            validate_file_size(payload, "huge.epub")
        assert exc_info.value.status_code == 413
        assert "exceeding" in exc_info.value.detail

    def test_exactly_at_limit(self, monkeypatch):
        monkeypatch.setattr("backend.app.upload_validation.MAX_UPLOAD_BYTES", 16)
        payload = b"x" * 16
        validate_file_size(payload, "exact.epub")  # should not raise


@pytest.mark.asyncio
async def test_read_upload_limited_stops_after_limit():
    class ChunkedUpload:
        def __init__(self):
            self.read_sizes = []

        async def read(self, size):
            self.read_sizes.append(size)
            return b"x" * size

    upload = ChunkedUpload()
    with pytest.raises(HTTPException) as exc_info:
        await read_upload_limited(upload, 8, "too-large.epub")

    assert exc_info.value.status_code == 413
    assert sum(upload.read_sizes) == 9


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

    def test_rejects_excessive_total_uncompressed_size(self, monkeypatch):
        monkeypatch.setattr("backend.app.upload_validation.MAX_ZIP_UNCOMPRESSED_BYTES", 4)
        payload = _make_zip({"large.txt": b"12345"})
        with pytest.raises(HTTPException) as exc_info:
            validate_zip_safety(payload, "expanded.zip")
        assert exc_info.value.status_code == 400
        assert "expands" in exc_info.value.detail


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

    def test_rejects_svg(self):
        with pytest.raises(HTTPException):
            validate_image_upload(b"<svg><script>alert(1)</script></svg>", "cover.svg")

    def test_rejects_non_webp_riff(self):
        assert detect_image_extension(b"RIFF\x10\x00\x00\x00WAVEfake") is None

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

    detect_image_extension,
    read_upload_limited,
