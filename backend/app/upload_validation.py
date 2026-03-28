"""Upload validation: magic bytes, size limits, and zip safety checks."""

import zipfile
from io import BytesIO

from fastapi import HTTPException, UploadFile, status

# EPUB files are ZIP archives; the first bytes are the PK zip signature.
_ZIP_MAGIC = b"PK\x03\x04"
_ZIP_MAGIC_EMPTY = b"PK\x05\x06"  # empty archive

# Maximum upload sizes
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
MAX_ZIP_ENTRIES = 5000  # max files inside a ZIP/EPUB
MAX_ZIP_UNCOMPRESSED_RATIO = 100  # compressed-to-uncompressed ratio (zip bomb detection)
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB for cover images

# Image magic bytes
_IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": "JPEG",
    b"\x89PNG\r\n\x1a\n": "PNG",
    b"RIFF": "WEBP",  # WEBP starts with RIFF....WEBP
    b"GIF87a": "GIF",
    b"GIF89a": "GIF",
}


def validate_magic_bytes(payload: bytes, filename: str) -> None:
    """Raise 400 if payload doesn't start with a valid ZIP/EPUB signature."""
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Uploaded file '{filename}' is empty.",
        )
    if not (payload[:4] == _ZIP_MAGIC or payload[:4] == _ZIP_MAGIC_EMPTY):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Uploaded file '{filename}' is not a valid EPUB or ZIP file.",
        )


def validate_file_size(payload: bytes, filename: str) -> None:
    """Raise 413 if payload exceeds the maximum upload size."""
    if len(payload) > MAX_UPLOAD_BYTES:
        size_mb = len(payload) / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded file '{filename}' is {size_mb:.1f} MB, exceeding the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )


def validate_zip_safety(payload: bytes, filename: str) -> None:
    """Check ZIP internals for excessive entry count or zip bomb characteristics."""
    try:
        with zipfile.ZipFile(BytesIO(payload)) as zf:
            entries = zf.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"'{filename}' contains {len(entries)} entries, exceeding the {MAX_ZIP_ENTRIES} entry limit.",
                )

            compressed_size = sum(e.compress_size for e in entries)
            uncompressed_size = sum(e.file_size for e in entries)
            if compressed_size > 0 and uncompressed_size / compressed_size > MAX_ZIP_UNCOMPRESSED_RATIO:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"'{filename}' has a suspicious compression ratio (possible zip bomb).",
                )

            # Check for path traversal in entry names
            for entry in entries:
                name = entry.filename
                if name.startswith("/") or ".." in name.split("/"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"'{filename}' contains an entry with an unsafe path: '{name}'.",
                    )
    except zipfile.BadZipFile as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{filename}' is not a valid ZIP file: {e}",
        ) from e


def validate_upload(payload: bytes, filename: str) -> None:
    """Run all upload validations on a file payload."""
    validate_file_size(payload, filename)
    validate_magic_bytes(payload, filename)
    validate_zip_safety(payload, filename)


async def read_and_validate_upload(file: UploadFile) -> bytes:
    """Read an UploadFile and run all validations. Returns the raw bytes."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is missing a filename.",
        )
    payload = await file.read()
    validate_upload(payload, file.filename)
    return payload


def validate_image_upload(payload: bytes, filename: str) -> None:
    """Validate an image upload (for cover images)."""
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Uploaded file '{filename}' is empty.",
        )
    if len(payload) > MAX_IMAGE_BYTES:
        size_mb = len(payload) / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image '{filename}' is {size_mb:.1f} MB, exceeding the {MAX_IMAGE_BYTES // (1024 * 1024)} MB limit.",
        )
    if not any(payload.startswith(sig) for sig in _IMAGE_SIGNATURES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Uploaded file '{filename}' is not a recognized image format (JPEG, PNG, WEBP, GIF).",
        )
