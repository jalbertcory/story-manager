"""Web novel download pipeline: FanFicFare integration, background tasks, and the 24h update job."""

import asyncio
import logging
import shutil
import traceback
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ebooklib import epub
from fastapi import HTTPException, status
from lxml import etree

from .. import crud, epub_editor, models, schemas
from ..config import LIBRARY_PATH
from ..database import SessionLocal
from .cover_collectors import collect_cover
from .epub_utils import (
    get_and_save_epub_cover,
    get_epub_tag_metadata,
    get_epub_word_and_chapter_count,
    normalize_epub_prose_blocks,
)
from .fanficfare_config import get_fff_config_paths
from .library_paths import build_book_paths
from .metadata_jobs import queue_metadata_sync_job

logger = logging.getLogger(__name__)

# Module-level lock to serialize all FanFicFare downloads.
# A fresh asyncio.Lock() inside download_web_novel would create a new lock per
# call, defeating the purpose. This single lock ensures only one FFF invocation
# runs at a time, preventing the before/after EPUB-detection race condition.
_fff_lock = asyncio.Lock()


def _run_fff_main(args: List[str]) -> int:
    """Wrapper for fff_main that converts SystemExit into a return code."""
    from fanficfare.cli import main as fff_main

    try:
        fff_main(args)
        return 0
    except SystemExit as e:
        return e.code if e.code is not None else 0
    except Exception as e:
        logger.error(f"An unexpected error occurred in FanFicFare: {e}")
        return 1


def _get_story_manager_output_filename() -> str:
    return str((LIBRARY_PATH / "${title}-${siteabbrev}_${storyId}${formatext}").resolve())


def _get_epub_state(epub_path: Path) -> Optional[tuple[int, int]]:
    if not epub_path.exists():
        return None
    stat = epub_path.stat()
    return stat.st_mtime_ns, stat.st_size


def _read_epub_metadata(epub_path: Path) -> Dict[str, Any]:
    book = epub.read_epub(epub_path)
    title = book.get_metadata("DC", "title")[0][0]
    author = book.get_metadata("DC", "creator")[0][0]
    try:
        series_metadata = book.get_metadata("calibre", "series")
    except KeyError:
        series_metadata = []
    series = series_metadata[0][0] if series_metadata else None
    metadata = {"title": title, "author": author, "series": series}
    tag_metadata = get_epub_tag_metadata(epub_path)
    if tag_metadata["genre_tags"]:
        metadata["genre_tags"] = tag_metadata["genre_tags"]
    if tag_metadata["source_tags"]:
        metadata["source_tags"] = tag_metadata["source_tags"]
    return metadata


def _get_rootfile_path(epub_path: Path) -> str:
    with zipfile.ZipFile(epub_path) as archive:
        container = etree.fromstring(archive.read("META-INF/container.xml"))
    return container.xpath(
        "/u:container/u:rootfiles/u:rootfile",
        namespaces={"u": "urn:oasis:names:tc:opendocument:xmlns:container"},
    )[0].get("full-path")


def _get_epub_source_url(epub_path: Path) -> Optional[str]:
    try:
        rootfile_path = _get_rootfile_path(epub_path)
        with zipfile.ZipFile(epub_path) as archive:
            package = etree.fromstring(archive.read(rootfile_path))
        matches = package.xpath(
            "/opf:package/opf:metadata/dc:source",
            namespaces={
                "opf": "http://www.idpf.org/2007/opf",
                "dc": "http://purl.org/dc/elements/1.1/",
            },
        )
        if not matches:
            return None
        value = (matches[0].text or "").strip()
        return value or None
    except Exception as exc:
        logger.warning("Failed reading dc:source from %s: %s", epub_path, exc)
        return None


def _sync_epub_source_url(epub_path: Path, source_url: str) -> None:
    existing_source_url = _get_epub_source_url(epub_path)
    if existing_source_url == source_url:
        return

    rootfile_path = _get_rootfile_path(epub_path)
    temp_path = epub_path.with_suffix(f"{epub_path.suffix}.tmp")

    with zipfile.ZipFile(epub_path) as src, zipfile.ZipFile(temp_path, "w") as dst:
        package = etree.fromstring(src.read(rootfile_path))
        metadata_nodes = package.xpath(
            "/opf:package/opf:metadata",
            namespaces={"opf": "http://www.idpf.org/2007/opf"},
        )
        if not metadata_nodes:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"EPUB metadata is missing from {epub_path}.",
            )

        metadata_node = metadata_nodes[0]
        source_nodes = package.xpath(
            "/opf:package/opf:metadata/dc:source",
            namespaces={
                "opf": "http://www.idpf.org/2007/opf",
                "dc": "http://purl.org/dc/elements/1.1/",
            },
        )
        if source_nodes:
            source_node = source_nodes[0]
        else:
            source_node = etree.SubElement(
                metadata_node,
                "{http://purl.org/dc/elements/1.1/}source",
            )
        source_node.text = source_url

        for info in src.infolist():
            data = (
                etree.tostring(package, encoding="utf-8", xml_declaration=True)
                if info.filename == rootfile_path
                else src.read(info.filename)
            )
            dst.writestr(info, data)

    temp_path.replace(epub_path)
    logger.info(
        "Synchronized EPUB dc:source for %s from %r to %r.",
        epub_path,
        existing_source_url,
        source_url,
    )


async def download_web_novel(
    source_url: str,
    overwrite: bool = False,
    existing_epub_path: Optional[Path] = None,
) -> Optional[tuple[Path, Dict[str, Any]]]:
    """
    Downloads a web novel via FanFicFare and returns (epub_path, metadata) or None.

    Returns None only when overwrite=False and FFF determines the story has not been
    updated since the last download. If existing_epub_path is provided, FFF updates
    that EPUB in place using -u/-U and reuses previously downloaded chapters.
    """
    LIBRARY_PATH.mkdir(exist_ok=True)
    config_paths = get_fff_config_paths()

    async with _fff_lock:
        args: List[str] = []
        for config_path in config_paths:
            args.extend(["-c", str(config_path)])
        args.extend(["--non-interactive", "--debug"])

        changed_epubs: List[Path] = []
        updated_epub_path: Optional[Path] = None

        if existing_epub_path is not None:
            updated_epub_path = existing_epub_path.resolve()
            if not updated_epub_path.is_file():
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Expected existing EPUB for update, but none was found at {updated_epub_path}.",
                )
            _sync_epub_source_url(updated_epub_path, source_url)
            before_state = _get_epub_state(updated_epub_path)
            args.append("-U" if overwrite else "-u")
            args.append(str(updated_epub_path))
        else:
            before_epubs = {f: f.stat().st_mtime for f in LIBRARY_PATH.iterdir() if f.suffix == ".epub"}
            args.extend(["-o", f"output_filename={_get_story_manager_output_filename()}"])
            if overwrite:
                args.extend(["-o", "always_overwrite=true"])
            args.append(source_url)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_fff_main, args)

        if result != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"FanFicFare failed to download story. Error code: {result}.",
            )

        if updated_epub_path is not None:
            after_state = _get_epub_state(updated_epub_path)
            if after_state == before_state and not overwrite:
                return None
        else:
            changed_epubs = [
                f
                for f in LIBRARY_PATH.iterdir()
                if f.suffix == ".epub" and (f not in before_epubs or f.stat().st_mtime > before_epubs[f])
            ]

    if updated_epub_path is None and not changed_epubs:
        if not overwrite:
            return None
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FanFicFare ran but no new or updated EPUB file was found.",
        )
    new_epub_path = updated_epub_path or changed_epubs[0]
    normalize_epub_prose_blocks(new_epub_path)

    try:
        return new_epub_path, _read_epub_metadata(new_epub_path)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse EPUB metadata: {e}",
        )


async def finish_web_novel_download(book_id: int, source_url: str) -> None:
    """Background task: downloads the EPUB for a pending book and updates the DB record."""
    async with SessionLocal() as db:
        db_book = await crud.get_book(db, book_id=book_id)
        if db_book is None:
            logger.error(f"Background download: book {book_id} not found")
            return

        chapter_count = 0
        master_word_count = 0
        try:
            result = await download_web_novel(source_url)
            if result is None:
                db_book.download_status = "error"
                db_book.title = "Error: FFF produced no epub for new URL"
                await db.commit()
                return
            new_epub_path, metadata = result

            existing = await crud.get_book_by_title_and_author(db, title=metadata["title"], author=metadata["author"])
            if existing and existing.id != book_id and existing.source_type == models.SourceType.web:
                new_epub_path.unlink(missing_ok=True)
                db_book.download_status = "error"
                db_book.title = f"Conflict: '{metadata['title']}' already exists"
                await db.commit()
                return

            immutable_path, current_path = build_book_paths(new_epub_path.name, metadata["author"])
            new_epub_path.rename(immutable_path)
            shutil.copyfile(immutable_path, current_path)

            master_word_count = epub_editor.get_word_count(str(immutable_path))
            _, chapter_count = get_epub_word_and_chapter_count(current_path)

            db_book.title = metadata["title"]
            db_book.author = metadata["author"]
            db_book.series = metadata["series"]
            db_book.genre_tags = metadata.get("genre_tags") or []
            db_book.source_tags = metadata.get("source_tags") or []
            db_book.immutable_path = str(immutable_path.relative_to(LIBRARY_PATH.parent))
            db_book.current_path = str(current_path.relative_to(LIBRARY_PATH.parent))
            db_book.master_word_count = master_word_count
            db_book.current_word_count = master_word_count
            await crud.touch_book_content(db, db_book)

            cover_path = get_and_save_epub_cover(epub_path=immutable_path, book_id=db_book.id)
            if cover_path is None:
                cover_path = await collect_cover(source_url, db_book.id)
            if cover_path:
                db_book.cover_path = str(cover_path.relative_to(LIBRARY_PATH.parent))

            db_book.download_status = None
            await db.commit()
            await db.refresh(db_book)

        except Exception as e:
            logger.error(f"Background download failed for book {book_id}: {e}\n{traceback.format_exc()}")
            try:
                db_book.download_status = "error"
                db_book.title = "Download failed"
                await db.commit()
            except Exception:
                pass
            return

        # Post-commit: log the addition and apply cleaning
        log_entry = schemas.BookLogCreate(
            book_id=db_book.id,
            entry_type="added",
            new_chapter_count=chapter_count,
            words_added=master_word_count,
        )
        await crud.create_book_log(db, log_entry)
        await db.refresh(db_book)
        await epub_editor.apply_book_cleaning(db_book, db)
        await queue_metadata_sync_job(db, trigger="new_book", book_ids=[db_book.id])


async def run_book_refresh(book_id: int) -> None:
    """Re-download a single web novel from its source URL and apply cleaning.

    This mirrors what the scheduled ``update_web_novels`` job does for one book,
    but also handles web imports that never finished their initial download
    (no ``immutable_path``/``current_path``). Updates ``book.refresh_status``
    throughout: "processing" while running, ``None`` on success, and "error"
    on any failure.
    """
    async with SessionLocal() as db:
        db_book = await crud.get_book(db, book_id=book_id)
        if db_book is None:
            logger.error("Refresh worker: book %s not found.", book_id)
            return
        if not db_book.source_url:
            logger.warning("Refresh worker: book %s has no source_url.", book_id)
            db_book.refresh_status = "error"
            await db.commit()
            return

        db_book.refresh_status = "processing"
        await db.commit()
        await db.refresh(db_book)

        try:
            if not db_book.immutable_path or not db_book.current_path:
                result = await download_web_novel(db_book.source_url, overwrite=True)
                if result is None:
                    raise RuntimeError("FanFicFare did not produce a refreshed EPUB.")
                new_epub_path, metadata = result

                immutable_path, current_path = build_book_paths(new_epub_path.name, metadata["author"])
                new_epub_path.rename(immutable_path)
                shutil.copyfile(immutable_path, current_path)

                new_word_count, new_chapter_count = get_epub_word_and_chapter_count(current_path)
                update_data = schemas.BookUpdate(**metadata)
                updated_book = await crud.update_book(db=db, book=db_book, update_data=update_data)
                updated_book.removed_chapters = []
                updated_book.master_word_count = new_word_count
                updated_book.current_word_count = new_word_count
                updated_book.immutable_path = str(immutable_path.relative_to(LIBRARY_PATH.parent))
                updated_book.current_path = str(current_path.relative_to(LIBRARY_PATH.parent))
                updated_book.download_status = None
                await crud.touch_book_content(db, updated_book)
                await db.commit()
                await db.refresh(updated_book)

                log_entry = schemas.BookLogCreate(
                    book_id=updated_book.id,
                    entry_type="updated",
                    previous_chapter_count=0,
                    new_chapter_count=new_chapter_count,
                    words_added=new_word_count,
                )
                await crud.create_book_log(db, log_entry)
                await epub_editor.apply_book_cleaning(updated_book, db)
                await queue_metadata_sync_job(db, trigger="book_update", book_ids=[updated_book.id])

                updated_book.refresh_status = None
                await db.commit()
                return

            immutable_path = LIBRARY_PATH.parent / db_book.immutable_path
            current_path = LIBRARY_PATH.parent / db_book.current_path

            old_word_count, old_chapter_count = get_epub_word_and_chapter_count(current_path)
            result = await download_web_novel(db_book.source_url, overwrite=True, existing_epub_path=immutable_path)
            if result is None:
                raise RuntimeError("FanFicFare did not update the existing EPUB during refresh.")
            new_epub_path, metadata = result

            if new_epub_path != immutable_path:
                new_epub_path.rename(immutable_path)
            shutil.copyfile(immutable_path, current_path)

            new_word_count, new_chapter_count = get_epub_word_and_chapter_count(current_path)

            if new_chapter_count > old_chapter_count:
                logger.info(
                    "Found %s new chapters for %s.",
                    new_chapter_count - old_chapter_count,
                    db_book.title,
                )
                log_entry = schemas.BookLogCreate(
                    book_id=db_book.id,
                    entry_type="updated",
                    previous_chapter_count=old_chapter_count,
                    new_chapter_count=new_chapter_count,
                    words_added=new_word_count - old_word_count,
                )
                await crud.create_book_log(db, log_entry)

            update_data = schemas.BookUpdate(**metadata)
            updated_book = await crud.update_book(db=db, book=db_book, update_data=update_data)

            # Reset per-source processing state; preserve per-book content_selectors
            updated_book.removed_chapters = []
            updated_book.master_word_count = new_word_count
            updated_book.current_word_count = new_word_count
            await crud.touch_book_content(db, updated_book)
            await db.commit()
            await db.refresh(updated_book)

            await epub_editor.apply_book_cleaning(updated_book, db)
            await queue_metadata_sync_job(db, trigger="book_update", book_ids=[updated_book.id])

            updated_book.refresh_status = None
            await db.commit()
        except Exception as exc:
            logger.error(
                "Manual refresh failed for book %s: %s\n%s",
                book_id,
                exc,
                traceback.format_exc(),
            )
            try:
                db_book.refresh_status = "error"
                await db.commit()
            except Exception:
                logger.exception("Failed to mark refresh_status=error for book %s", book_id)


async def update_web_novels() -> None:
    """Scheduler job: checks all web novels for updates every 24 hours."""
    logger.info("Starting web novel update job.")
    db = SessionLocal()
    task = None
    failed = False
    had_book_failures = False
    try:
        books = await crud.get_web_books(db)
        task = await crud.get_active_update_task(db)
        if task is not None:
            logger.info("Skipping web novel update because task %s is already running.", task.id)
            return
        task = await crud.create_update_task(db, total_books=len(books))
        logger.info(f"Update task {task.id} processing {task.completed_books}/{task.total_books} books.")

        for book in books:
            old_chapter_count: Optional[int] = None
            try:
                if not book.immutable_path or not book.current_path:
                    logger.warning("Skipping %s (id=%s): missing epub paths.", book.title, book.id)
                    continue

                latest_log = await crud.get_latest_book_log(db, book.id)
                if latest_log and latest_log.timestamp >= task.started_at:
                    logger.info(f"Skipping {book.title}, already processed in this task.")
                    continue

                logger.info(f"Checking {book.title} for updates.")
                immutable_path = LIBRARY_PATH.parent / book.immutable_path
                current_path = LIBRARY_PATH.parent / book.current_path

                old_word_count, old_chapter_count = get_epub_word_and_chapter_count(immutable_path)
                result = await download_web_novel(book.source_url, existing_epub_path=immutable_path)

                if result is None:
                    logger.info(f"No update available for {book.title} (FFF skipped).")
                    log_entry = schemas.BookLogCreate(
                        book_id=book.id,
                        entry_type="checked",
                        previous_chapter_count=old_chapter_count,
                        new_chapter_count=old_chapter_count,
                        words_added=0,
                    )
                    await crud.create_book_log(db, log_entry)
                    continue

                new_epub_path, _ = result
                if new_epub_path != immutable_path:
                    new_epub_path.rename(immutable_path)
                shutil.copyfile(immutable_path, current_path)

                new_word_count, new_chapter_count = get_epub_word_and_chapter_count(immutable_path)

                if new_chapter_count > old_chapter_count:
                    logger.info(f"Found {new_chapter_count - old_chapter_count} new chapters for {book.title}.")
                    log_entry = schemas.BookLogCreate(
                        book_id=book.id,
                        entry_type="updated",
                        previous_chapter_count=old_chapter_count,
                        new_chapter_count=new_chapter_count,
                        words_added=new_word_count - old_word_count,
                    )
                    book.master_word_count = new_word_count
                    book.current_word_count = new_word_count
                    await crud.touch_book_content(db, book)
                    await db.commit()
                else:
                    logger.info(f"No new chapters for {book.title}.")
                    log_entry = schemas.BookLogCreate(
                        book_id=book.id,
                        entry_type="checked",
                        previous_chapter_count=old_chapter_count,
                        new_chapter_count=new_chapter_count,
                        words_added=0,
                    )
                await crud.create_book_log(db, log_entry)
                await epub_editor.apply_book_cleaning(book, db)
            except Exception as e:
                had_book_failures = True
                logger.error(f"Failed to update {book.title}: {e}\n{traceback.format_exc()}")
                await crud.create_book_log(
                    db,
                    schemas.BookLogCreate(
                        book_id=book.id,
                        entry_type="error",
                        previous_chapter_count=old_chapter_count,
                        new_chapter_count=old_chapter_count,
                        words_added=0,
                    ),
                )
            finally:
                await crud.increment_update_task(db, task)
    except Exception as e:
        logger.error(f"Scheduler run failed: {e}\n{traceback.format_exc()}")
        failed = True
    finally:
        if task is not None:
            if failed or had_book_failures:
                await crud.fail_update_task(db, task)
            else:
                await crud.complete_update_task(db, task)
        await db.close()
