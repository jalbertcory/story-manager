"""EPUB upload endpoints: single file, multi-file batch, and library-wide series detection."""

import logging
from io import BytesIO
import zipfile
from pathlib import PurePosixPath
from collections.abc import Iterator
from typing import List, Optional

from ebooklib import epub
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, epub_editor, models, schemas
from ..config import LIBRARY_PATH
from ..database import get_db
from ..services.epub_utils import get_and_save_epub_cover, get_epub_tag_metadata, get_epub_word_and_chapter_count
from ..services.library_paths import build_book_paths
from ..services.metadata_jobs import queue_metadata_sync_job
from ..services.series import SeriesBook, detect_series_from_books
from ..upload_validation import MAX_UPLOAD_BYTES, read_and_validate_upload, read_upload_limited, validate_upload

logger = logging.getLogger(__name__)

router = APIRouter()


def _fix_nested_epub(payload: bytes) -> bytes:
    """If an EPUB has all files nested under a single subdirectory, repack with paths at root level."""
    try:
        with zipfile.ZipFile(BytesIO(payload)) as zin:
            names = zin.namelist()
            if "META-INF/container.xml" in names:
                return payload  # Already valid

            # Find container.xml nested in a subdirectory
            container_paths = [n for n in names if n.endswith("META-INF/container.xml")]
            if len(container_paths) != 1:
                return payload  # Can't determine prefix, return as-is

            # e.g. "BookName/META-INF/container.xml" -> prefix = "BookName/"
            prefix = container_paths[0].rsplit("META-INF/container.xml", 1)[0]
            if not prefix:
                return payload

            buf = BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    if item.is_dir():
                        continue
                    new_name = item.filename.removeprefix(prefix)
                    if not new_name:
                        continue
                    zout.writestr(new_name, zin.read(item.filename))
            return buf.getvalue()
    except Exception:
        return payload  # If anything goes wrong, return original


class EpubUploadResult(BaseModel):
    filename: str
    status: str  # "success" | "skipped" | "error"
    book: Optional[schemas.Book] = None
    error: Optional[str] = None


def _is_zip_upload(file: UploadFile) -> bool:
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    return filename.endswith(".zip") or content_type in {"application/zip", "application/x-zip-compressed"}


def _safe_batch_filename(name: str) -> str:
    path = PurePosixPath(name)
    parts = [part for part in path.parts if part not in {"", ".", ".."}]
    safe_name = "_".join(parts) if parts else "book.epub"
    return safe_name.replace("/", "_").replace("\\", "_")


def _extract_epubs_from_zip(zip_name: str, payload: bytes) -> Iterator[tuple[str, bytes, str]]:
    """Yield one validated EPUB at a time to avoid retaining a whole expanded batch."""
    try:
        with zipfile.ZipFile(file=BytesIO(payload)) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                entry_name = entry.filename
                if not entry_name.lower().endswith(".epub"):
                    continue

                relative_name = _safe_batch_filename(entry_name)
                display_name = f"{zip_name}:{entry_name}"
                if entry.file_size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"EPUB '{display_name}' exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                    )
                epub_payload = archive.read(entry)
                validate_upload(epub_payload, display_name)
                yield display_name, epub_payload, relative_name
    except zipfile.BadZipFile as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read ZIP file '{zip_name}': {e}",
        ) from e


async def _upload_epub_bytes(filename: str, payload: bytes, db: AsyncSession) -> models.Book:
    """
    Saves an EPUB to the library, extracts metadata, creates a DB record,
    saves the cover, logs the addition, and applies cleaning.
    Raises HTTPException on duplicate or parse errors.
    """
    payload = _fix_nested_epub(payload)
    # Strip any path components from the filename — some browsers (or the FileSystem API)
    # may send a relative path like "folder/book.epub" instead of just "book.epub".
    safe_filename = PurePosixPath(filename or "upload.epub").name or "upload.epub"
    LIBRARY_PATH.mkdir(exist_ok=True)
    temp_immutable_path = LIBRARY_PATH / f"tmp_immutable_{safe_filename}"
    temp_current_path = LIBRARY_PATH / f"tmp_{safe_filename}"
    with open(temp_immutable_path, "wb+") as f:
        f.write(payload)

    with open(temp_current_path, "wb+") as f:
        f.write(payload)

    try:
        epub_book = epub.read_epub(temp_immutable_path)
        title = epub_book.get_metadata("DC", "title")[0][0]
        author = epub_book.get_metadata("DC", "creator")[0][0]
    except Exception as e:
        temp_immutable_path.unlink(missing_ok=True)
        temp_current_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse EPUB file: {e}",
        )

    existing = await crud.get_book_by_title_and_author(db, title=title, author=author)
    if existing and existing.source_type == models.SourceType.epub:
        # Check if the existing book's files are missing — if so, restore them
        # from the upload instead of rejecting as a duplicate.
        files_intact = True
        if existing.immutable_path:
            files_intact = files_intact and (LIBRARY_PATH.parent / existing.immutable_path).exists()
        else:
            files_intact = False
        if existing.current_path:
            files_intact = files_intact and (LIBRARY_PATH.parent / existing.current_path).exists()
        else:
            files_intact = False

        if files_intact:
            temp_immutable_path.unlink(missing_ok=True)
            temp_current_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A book with title '{title}' by '{author}' already exists (id={existing.id})",
            )

        # Restore missing files for the existing book record.
        logger.info("Restoring missing files for '%s' by '%s' (id=%s)", title, author, existing.id)
        immutable_path, current_path = build_book_paths(f"{title} - {author}.epub", author)
        temp_immutable_path.replace(immutable_path)
        temp_current_path.replace(current_path)

        existing.immutable_path = str(immutable_path.relative_to(LIBRARY_PATH.parent))
        existing.current_path = str(current_path.relative_to(LIBRARY_PATH.parent))
        existing.master_word_count = epub_editor.get_word_count(str(immutable_path))
        existing.current_word_count = existing.master_word_count

        if not existing.cover_path or not (LIBRARY_PATH.parent / existing.cover_path).exists():
            cover_path = get_and_save_epub_cover(epub_path=immutable_path, book_id=existing.id)
            if cover_path:
                existing.cover_path = str(cover_path.relative_to(LIBRARY_PATH.parent))

        await db.commit()
        await db.refresh(existing)
        await epub_editor.apply_book_cleaning(existing, db)
        return existing

    immutable_path, current_path = build_book_paths(f"{title} - {author}.epub", author)
    temp_immutable_path.replace(immutable_path)
    temp_current_path.replace(current_path)

    try:
        series_metadata = epub_book.get_metadata("calibre", "series")
        series = series_metadata[0][0] if series_metadata else None
    except Exception as e:
        logger.warning(f"Failed to parse series metadata: {e}")
        series = None

    source_url: Optional[str] = None
    source_type = models.SourceType.epub
    try:
        dc_source = epub_book.get_metadata("DC", "source")
        if dc_source:
            raw_url = dc_source[0][0]
            if isinstance(raw_url, str) and raw_url.lower().startswith(("http://", "https://")):
                source_url = raw_url
                source_type = models.SourceType.web
                logger.info(f"Detected FFF epub with source URL: {source_url}")
            else:
                logger.info(f"Skipping non-HTTP dc:source metadata: {raw_url}")
    except Exception as e:
        logger.warning(f"Failed to parse dc:source metadata: {e}")

    master_word_count = epub_editor.get_word_count(str(immutable_path))
    tag_metadata = get_epub_tag_metadata(immutable_path)

    book_to_create = schemas.BookCreate(
        title=title,
        author=author,
        series=series,
        genre_tags=tag_metadata["genre_tags"],
        source_tags=tag_metadata["source_tags"],
        immutable_path=str(immutable_path.relative_to(LIBRARY_PATH.parent)),
        current_path=str(current_path.relative_to(LIBRARY_PATH.parent)),
        source_url=source_url,
        source_type=source_type,
        master_word_count=master_word_count,
        current_word_count=master_word_count,
    )

    try:
        db_book = await crud.create_book(db=db, book=book_to_create)
    except IntegrityError:
        await db.rollback()
        immutable_path.unlink(missing_ok=True)
        current_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A book with title '{title}' by '{author}' already exists at the target path",
        )

    cover_path = get_and_save_epub_cover(epub_path=immutable_path, book_id=db_book.id)
    if cover_path:
        db_book.cover_path = str(cover_path.relative_to(LIBRARY_PATH.parent))
        await db.commit()
        await db.refresh(db_book)

    _, chapter_count = get_epub_word_and_chapter_count(current_path)
    log_entry = schemas.BookLogCreate(
        book_id=db_book.id,
        entry_type="added",
        new_chapter_count=chapter_count,
        words_added=master_word_count,
    )
    await crud.create_book_log(db, log_entry)

    await db.refresh(db_book)
    await epub_editor.apply_book_cleaning(db_book, db)

    return db_book


async def _upload_epub_file(file: UploadFile, db: AsyncSession) -> models.Book:
    payload = await read_and_validate_upload(file)
    return await _upload_epub_bytes(file.filename, payload, db)


@router.post(
    "/api/books/upload_epub",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.Book,
)
async def upload_epub(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)) -> models.Book:
    """Uploads a single EPUB file, extracts metadata, and adds it to the database."""
    book = await _upload_epub_file(file, db)
    await queue_metadata_sync_job(db, trigger="new_book", book_ids=[book.id])
    return book


@router.post("/api/books/upload_epubs", response_model=List[EpubUploadResult])
async def upload_epubs(files: List[UploadFile] = File(...), db: AsyncSession = Depends(get_db)) -> List[EpubUploadResult]:
    """
    Uploads multiple EPUB files. After processing all files, auto-detects series groupings
    among books with no series metadata using the pattern "<series name> <number> [- <subtitle>]".
    """
    results: List[EpubUploadResult] = []
    created_books: List[models.Book] = []

    for file in files:
        try:
            if _is_zip_upload(file):
                archive_name = file.filename or "upload.zip"
                zip_payload = await read_upload_limited(file, MAX_UPLOAD_BYTES, archive_name)
                validate_upload(zip_payload, archive_name)
                epub_entries = _extract_epubs_from_zip(archive_name, zip_payload)
                found_epub = False
                for display_name, payload, safe_name in epub_entries:
                    found_epub = True
                    try:
                        db_book = await _upload_epub_bytes(safe_name, payload, db)
                        results.append(EpubUploadResult(filename=display_name, status="success", book=db_book))
                        created_books.append(db_book)
                    except HTTPException as e:
                        status_str = "skipped" if e.status_code == 409 else "error"
                        results.append(EpubUploadResult(filename=display_name, status=status_str, error=e.detail))
                    except Exception as e:
                        results.append(EpubUploadResult(filename=display_name, status="error", error=str(e)))

                if not found_epub:
                    results.append(
                        EpubUploadResult(
                            filename=archive_name,
                            status="skipped",
                            error="No EPUB files found in ZIP archive",
                        )
                    )
                continue

            db_book = await _upload_epub_file(file, db)
            results.append(EpubUploadResult(filename=file.filename, status="success", book=db_book))
            created_books.append(db_book)
        except HTTPException as e:
            status_str = "skipped" if e.status_code == 409 else "error"
            results.append(EpubUploadResult(filename=file.filename or "upload", status=status_str, error=e.detail))
        except Exception as e:
            results.append(EpubUploadResult(filename=file.filename or "upload", status="error", error=str(e)))

    # Detect series across the batch AND existing library books without a series.
    batch_ids = {b.id for b in created_books}
    batch_no_series = [b for b in created_books if not b.series]
    existing_no_series = [b for b in await crud.get_books_without_series(db) if b.id not in batch_ids]
    all_candidates = batch_no_series + existing_no_series

    if len(all_candidates) >= 2:
        series_map = detect_series_from_books([SeriesBook(title=b.title, author=b.author) for b in all_candidates])
        updated = [b for b in all_candidates if (b.author, b.title) in series_map]
        if updated:
            for b in updated:
                b.series = series_map[(b.author, b.title)]
            await db.commit()
            for b in updated:
                await db.refresh(b)
            logger.info(
                f"Auto-detected series for {len(updated)} books: " + ", ".join(f"'{b.title}' → '{b.series}'" for b in updated)
            )

    if created_books:
        await queue_metadata_sync_job(db, trigger="new_book", book_ids=[book.id for book in created_books])

    return results


@router.post("/api/books/detect-series")
async def detect_series_in_library(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Scans all books without an assigned series and auto-detects groupings
    using title patterns like "<series> <number> [- <subtitle>]".
    """
    candidates = await crud.get_books_without_series(db)
    if len(candidates) < 2:
        return {"updated": 0, "series_detected": []}

    series_map = detect_series_from_books([SeriesBook(title=b.title, author=b.author) for b in candidates])
    to_update = [b for b in candidates if (b.author, b.title) in series_map]

    if not to_update:
        return {"updated": 0, "series_detected": []}

    for b in to_update:
        b.series = series_map[(b.author, b.title)]
    await db.commit()

    series_detected = sorted(set(series_map.values()))
    logger.info(f"detect-series: updated {len(to_update)} books, series: {series_detected}")
    return {"updated": len(to_update), "series_detected": series_detected}
