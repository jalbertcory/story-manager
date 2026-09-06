"""EPUB upload endpoints: single file, multi-file batch, and library-wide series detection."""

import logging
from io import BytesIO
import zipfile
from pathlib import Path, PurePosixPath
from collections.abc import Iterator
from typing import List, Optional

from ebooklib import epub
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, epub_editor, models, schemas
from ..config import LIBRARY_PATH
from ..database import get_db
from ..services.epub_utils import get_and_save_epub_cover, get_epub_tag_metadata, get_epub_word_and_chapter_count
from ..services.library_paths import build_book_paths
from ..services.book_matching import epub_identifiers, match_epub_to_audio_book
from ..services.metadata_jobs import queue_metadata_sync_job
from ..services.series import enrich_series_metadata
from ..services.processing_queue import queue_audio_reconciliation
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


class ImportPreviewItem(BaseModel):
    key: str
    input_type: str
    name: str
    status: str
    title: Optional[str] = None
    author: Optional[str] = None
    series: Optional[str] = None
    source_url: Optional[str] = None
    duplicate_book_id: Optional[int] = None
    cleaning_configs: list[str] = Field(default_factory=list)
    detail: Optional[str] = None


class ImportPreviewResponse(BaseModel):
    items: list[ImportPreviewItem]
    ready_count: int
    duplicate_count: int
    unsupported_count: int
    error_count: int


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


async def _existing_epub_target(db: AsyncSession, ebook: epub.EpubBook, title: str, author: str) -> models.Book | None:
    existing = await crud.get_book_by_title_and_author(db, title=title, author=author)
    if existing and (existing.deleted_at is not None or existing.source_type != models.SourceType.audiobook):
        return existing
    return await match_epub_to_audio_book(db, ebook, title, author)


async def _attach_epub_to_audio_book(
    book: models.Book, ebook: epub.EpubBook, title: str, author: str, original: Path, current: Path, db: AsyncSession
) -> models.Book:
    # Include the existing ID in the filename so a same-title EPUB elsewhere in
    # the library cannot be overwritten when adding this book's text.
    immutable_path, current_path = build_book_paths(f"{title} - {author} - book {book.id}.epub", author)
    original.replace(immutable_path)
    current.replace(current_path)
    book.immutable_path = str(immutable_path.relative_to(LIBRARY_PATH.parent))
    book.current_path = str(current_path.relative_to(LIBRARY_PATH.parent))
    book.source_type = models.SourceType.epub
    book.master_word_count = epub_editor.get_word_count(str(immutable_path))
    book.current_word_count = book.master_word_count
    if not book.author or book.author == "Unknown author":
        book.author = author
    if not book.series:
        book.series = _first_epub_metadata(ebook, "calibre", "series")
    tags = get_epub_tag_metadata(immutable_path)
    book.genre_tags = sorted(set(book.genre_tags or []) | set(tags["genre_tags"]))
    book.source_tags = sorted(set(book.source_tags or []) | set(tags["source_tags"]))
    identifiers = epub_identifiers(ebook)
    book.metadata_remote_ids = {**identifiers, **(book.metadata_remote_ids or {})}
    book.metadata_details = {
        **(book.metadata_details or {}),
        "epub_attachment": {"title": title, "author": author, "identifiers": identifiers},
    }
    if not book.cover_path or not (LIBRARY_PATH.parent / book.cover_path).is_file():
        cover = get_and_save_epub_cover(epub_path=immutable_path, book_id=book.id)
        if cover:
            book.cover_path = str(cover.relative_to(LIBRARY_PATH.parent))
    await crud.touch_book_content(db, book)
    await db.commit()
    await db.refresh(book)
    await epub_editor.apply_book_cleaning(book, db)
    # Audio-only editions already have a matched_content_version. Always bump
    # the text version above and reconcile, even when no cleaning was needed.
    await queue_audio_reconciliation(book, db)
    _, chapter_count = get_epub_word_and_chapter_count(current_path)
    await crud.create_book_log(
        db,
        schemas.BookLogCreate(
            book_id=book.id,
            entry_type="updated",
            new_chapter_count=chapter_count,
            words_added=book.master_word_count,
        ),
    )
    return book


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

    try:
        existing = await _existing_epub_target(db, epub_book, title, author)
    except ValueError as exc:
        temp_immutable_path.unlink(missing_ok=True)
        temp_current_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if existing and existing.deleted_at is not None:
        temp_immutable_path.unlink(missing_ok=True)
        temp_current_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{title}' by '{author}' is in the recycle bin. Restore it or permanently delete it before importing again."
            ),
        )
    if existing and existing.source_type == models.SourceType.audiobook and not existing.current_path:
        return await _attach_epub_to_audio_book(existing, epub_book, title, author, temp_immutable_path, temp_current_path, db)
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
        changed = await epub_editor.apply_book_cleaning(existing, db)
        if changed:
            await queue_audio_reconciliation(existing, db)
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
        source_url=HttpUrl(source_url) if source_url is not None else None,
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
    assert file.filename is not None  # read_and_validate_upload rejects missing filenames.
    return await _upload_epub_bytes(file.filename, payload, db)


def _first_epub_metadata(epub_book: epub.EpubBook, namespace: str, key: str) -> Optional[str]:
    try:
        values = epub_book.get_metadata(namespace, key)
    except KeyError:
        return None
    if not values:
        return None
    value = values[0][0]
    return str(value).strip() if value is not None else None


async def _preview_epub_bytes(
    *,
    key: str,
    name: str,
    payload: bytes,
    db: AsyncSession,
    seen_books: set[tuple[str, str]],
) -> ImportPreviewItem:
    try:
        epub_book = epub.read_epub(BytesIO(_fix_nested_epub(payload)))
        title = _first_epub_metadata(epub_book, "DC", "title")
        author = _first_epub_metadata(epub_book, "DC", "creator")
        series = _first_epub_metadata(epub_book, "calibre", "series")
        source_url = _first_epub_metadata(epub_book, "DC", "source")
        if source_url and not source_url.lower().startswith(("http://", "https://")):
            source_url = None
        if not title or not author:
            raise ValueError("EPUB metadata must include a title and author.")
    except Exception as exc:
        return ImportPreviewItem(
            key=key,
            input_type="epub",
            name=name,
            status="error",
            detail=f"Could not read EPUB metadata: {exc}",
        )

    normalized = (title.casefold(), author.casefold())
    try:
        existing_book = await _existing_epub_target(db, epub_book, title, author)
    except ValueError as exc:
        return ImportPreviewItem(
            key=key, input_type="epub", name=name, status="error", title=title, author=author, detail=str(exc)
        )
    existing = existing_book if existing_book and existing_book.source_type == models.SourceType.epub else None
    duplicate_in_batch = normalized in seen_books
    seen_books.add(normalized)
    configs = await crud.get_all_matching_cleaning_configs(db, source_url) if source_url else []
    duplicate_detail = None
    if existing:
        duplicate_detail = f"Already in the library as book {existing.id}."
    elif duplicate_in_batch:
        duplicate_detail = "The same title and author appear more than once in this import."

    return ImportPreviewItem(
        key=key,
        input_type="epub",
        name=name,
        status="duplicate" if duplicate_detail else "ready",
        title=title,
        author=author,
        series=series,
        source_url=source_url,
        duplicate_book_id=existing.id if existing else None,
        cleaning_configs=[config.name for config in configs],
        detail=duplicate_detail
        or (
            f'Attach EPUB to "{existing_book.title}" (book {existing_book.id}) and match its audio chapters.'
            if existing_book and existing_book.source_type == models.SourceType.audiobook
            else None
        ),
    )


@router.post("/api/imports/preview", response_model=ImportPreviewResponse)
async def preview_imports(
    files: List[UploadFile] = File(default=[]),
    urls: List[str] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
) -> ImportPreviewResponse:
    """Inspect book files and web URLs without creating records or queueing work."""
    items: list[ImportPreviewItem] = []
    seen_books: set[tuple[str, str]] = set()
    seen_urls: set[str] = set()

    for file_index, file in enumerate(files):
        filename = file.filename or f"upload-{file_index + 1}"
        lower_name = filename.lower()
        if not lower_name.endswith((".epub", ".zip")):
            items.append(
                ImportPreviewItem(
                    key=f"file:{file_index}",
                    input_type="file",
                    name=filename,
                    status="unsupported",
                    detail="Choose an EPUB or ZIP containing EPUB files.",
                )
            )
            continue

        try:
            if _is_zip_upload(file):
                payload = await read_upload_limited(file, MAX_UPLOAD_BYTES, filename)
                validate_upload(payload, filename)
                entry_count = 0
                for entry_index, (display_name, entry_payload, _safe_name) in enumerate(
                    _extract_epubs_from_zip(filename, payload)
                ):
                    entry_count += 1
                    items.append(
                        await _preview_epub_bytes(
                            key=f"file:{file_index}:{entry_index}",
                            name=display_name,
                            payload=entry_payload,
                            db=db,
                            seen_books=seen_books,
                        )
                    )
                if entry_count == 0:
                    items.append(
                        ImportPreviewItem(
                            key=f"file:{file_index}",
                            input_type="zip",
                            name=filename,
                            status="unsupported",
                            detail="No EPUB files were found in this ZIP archive.",
                        )
                    )
                continue

            payload = await read_and_validate_upload(file)
            items.append(
                await _preview_epub_bytes(
                    key=f"file:{file_index}",
                    name=filename,
                    payload=payload,
                    db=db,
                    seen_books=seen_books,
                )
            )
        except HTTPException as exc:
            items.append(
                ImportPreviewItem(
                    key=f"file:{file_index}",
                    input_type="file",
                    name=filename,
                    status="error",
                    detail=str(exc.detail),
                )
            )
        except Exception as exc:
            items.append(
                ImportPreviewItem(
                    key=f"file:{file_index}",
                    input_type="file",
                    name=filename,
                    status="error",
                    detail=str(exc),
                )
            )

    url_adapter = TypeAdapter(HttpUrl)
    for url_index, raw_url in enumerate(urls):
        candidate = raw_url.strip()
        if not candidate:
            continue
        try:
            normalized_url = str(url_adapter.validate_python(candidate))
        except ValidationError:
            items.append(
                ImportPreviewItem(
                    key=f"url:{url_index}",
                    input_type="web",
                    name=candidate,
                    status="error",
                    detail="Enter a valid HTTP or HTTPS web novel URL.",
                )
            )
            continue

        existing = await crud.get_book_by_source_url(db, source_url=normalized_url)
        duplicate_in_batch = normalized_url in seen_urls
        seen_urls.add(normalized_url)
        configs = await crud.get_all_matching_cleaning_configs(db, normalized_url)
        detail = None
        if existing:
            detail = f"This source is already attached to {existing.title}."
        elif duplicate_in_batch:
            detail = "This URL appears more than once in this import."
        items.append(
            ImportPreviewItem(
                key=f"url:{url_index}",
                input_type="web",
                name=normalized_url,
                status="duplicate" if detail else "ready",
                source_url=normalized_url,
                duplicate_book_id=existing.id if existing else None,
                cleaning_configs=[config.name for config in configs],
                detail=detail or "Metadata will be collected when the durable web import runs.",
            )
        )

    return ImportPreviewResponse(
        items=items,
        ready_count=sum(item.status == "ready" for item in items),
        duplicate_count=sum(item.status == "duplicate" for item in items),
        unsupported_count=sum(item.status == "unsupported" for item in items),
        error_count=sum(item.status == "error" for item in items),
    )


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
                        results.append(
                            EpubUploadResult(
                                filename=display_name, status="success", book=schemas.Book.model_validate(db_book)
                            )
                        )
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
            results.append(
                EpubUploadResult(
                    filename=file.filename or "upload", status="success", book=schemas.Book.model_validate(db_book)
                )
            )
            created_books.append(db_book)
        except HTTPException as e:
            status_str = "skipped" if e.status_code == 409 else "error"
            results.append(EpubUploadResult(filename=file.filename or "upload", status=status_str, error=e.detail))
        except Exception as e:
            results.append(EpubUploadResult(filename=file.filename or "upload", status="error", error=str(e)))

    # Detect series across the batch AND existing library books without a series,
    # and fill deterministic positions for uploaded books that already named a series.
    batch_ids = {b.id for b in created_books}
    existing_no_series = [b for b in await crud.get_books_without_series(db) if b.id not in batch_ids]
    all_candidates = created_books + existing_no_series

    updated = enrich_series_metadata(all_candidates)
    if updated:
        await db.commit()
        for b in updated:
            await db.refresh(b)
        logger.info(
            f"Auto-detected series metadata for {len(updated)} books: "
            + ", ".join(f"'{b.title}' → '{b.series}' #{b.series_index or '?'}" for b in updated)
        )

    if created_books:
        await queue_metadata_sync_job(db, trigger="new_book", book_ids=[book.id for book in created_books])

    return results


@router.post("/api/books/detect-series", response_model=dict)
async def detect_series_in_library(db: AsyncSession = Depends(get_db)) -> dict[str, int | list[str]]:
    """
    Scans all books without an assigned series and auto-detects groupings
    using title patterns like "<series> <number> [- <subtitle>]".
    """
    candidates = await crud.get_books(db, limit=100000)
    to_update = enrich_series_metadata(candidates)

    if not to_update:
        return {"updated": 0, "series_detected": []}

    await db.commit()

    series_detected = sorted({book.series for book in to_update if book.series})
    logger.info(f"detect-series: updated {len(to_update)} books, series: {series_detected}")
    return {"updated": len(to_update), "series_detected": series_detected}
