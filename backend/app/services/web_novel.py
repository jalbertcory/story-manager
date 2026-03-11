"""Web novel download pipeline: FanFicFare integration, background tasks, and the 24h update job."""

import asyncio
import logging
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests as http_requests
from bs4 import BeautifulSoup
from ebooklib import epub
from fastapi import HTTPException, status

from .. import crud, epub_editor, schemas
from ..config import LIBRARY_PATH
from ..database import SessionLocal
from .epub_utils import get_and_save_epub_cover, get_epub_word_and_chapter_count

logger = logging.getLogger(__name__)


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


async def download_web_novel(source_url: str, overwrite: bool = False) -> Optional[tuple[Path, Dict[str, Any]]]:
    """
    Downloads a web novel via FanFicFare and returns (epub_path, metadata) or None.

    Returns None only when overwrite=False and FFF determines the story has not been
    updated since the last download. Use overwrite=True to force a re-download.
    """
    from ..config import APP_DIR

    ini_path = APP_DIR / "personal.ini"
    LIBRARY_PATH.mkdir(exist_ok=True)

    if not ini_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error: personal.ini not found.",
        )

    async with asyncio.Lock():
        before_epubs = {f: f.stat().st_mtime for f in LIBRARY_PATH.iterdir() if f.suffix == ".epub"}
        args = [
            "-c",
            str(ini_path),
            "-o",
            f"output_dir={str(LIBRARY_PATH)}",
            "--non-interactive",
            "--debug",
        ]
        if overwrite:
            args += ["-o", "always_overwrite=true"]
        args.append(source_url)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_fff_main, args)

        if result != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"FanFicFare failed to download story. Error code: {result}.",
            )
        changed_epubs = [
            f
            for f in LIBRARY_PATH.iterdir()
            if f.suffix == ".epub" and (f not in before_epubs or f.stat().st_mtime > before_epubs[f])
        ]

    if not changed_epubs:
        if not overwrite:
            return None
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FanFicFare ran but no new or updated EPUB file was found.",
        )
    new_epub_path = changed_epubs[0]

    try:
        book = epub.read_epub(new_epub_path)
        title = book.get_metadata("DC", "title")[0][0]
        author = book.get_metadata("DC", "creator")[0][0]
        series_metadata = book.get_metadata("calibre", "series")
        series = series_metadata[0][0] if series_metadata else None
        return new_epub_path, {"title": title, "author": author, "series": series}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse EPUB metadata: {e}",
        )


async def save_cover_from_url(url: str, book_id: int) -> Optional[Path]:
    """Downloads an image from a URL and saves it as the book cover. Returns the path or None."""
    covers_path = (LIBRARY_PATH / "covers").resolve()
    covers_path.mkdir(exist_ok=True)

    def fetch():
        r = http_requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"}, stream=True)
        r.raise_for_status()
        data = b""
        for chunk in r.iter_content(8192):
            data += chunk
            if len(data) > 10 * 1024 * 1024:
                raise ValueError("Image exceeds 10 MB limit")
        return r.headers.get("Content-Type", ""), data

    try:
        loop = asyncio.get_running_loop()
        content_type, image_bytes = await loop.run_in_executor(None, fetch)
        ext_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }
        ext = ext_map.get(content_type.split(";")[0].strip()) or Path(url.split("?")[0]).suffix or ".jpg"
        save_path = covers_path / f"{book_id}{ext}"
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        return save_path
    except Exception as e:
        logger.error(f"Failed to download cover from {url}: {e}")
        return None


async def scrape_cover(source_url: str, book_id: int) -> Optional[Path]:
    """Scrapes a cover image from a supported site (currently Royal Road)."""
    if "royalroad.com" not in source_url:
        return None

    def fetch_page():
        r = http_requests.get(source_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return r.text

    try:
        loop = asyncio.get_running_loop()
        html = await loop.run_in_executor(None, fetch_page)
        soup = BeautifulSoup(html, "html.parser")
        img = soup.select_one("div.cover-art-container img.thumbnail")
        if not img or not img.get("src"):
            return None
        return await save_cover_from_url(img["src"], book_id)
    except Exception as e:
        logger.error(f"Failed to scrape cover from {source_url}: {e}")
        return None


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
            if existing and existing.id != book_id:
                new_epub_path.unlink(missing_ok=True)
                db_book.download_status = "error"
                db_book.title = f"Conflict: '{metadata['title']}' already exists"
                await db.commit()
                return

            immutable_path = LIBRARY_PATH / f"immutable_{new_epub_path.name}"
            current_path = LIBRARY_PATH / new_epub_path.name
            new_epub_path.rename(immutable_path)
            with open(immutable_path, "rb") as f_in, open(current_path, "wb") as f_out:
                f_out.write(f_in.read())

            master_word_count = epub_editor.get_word_count(str(immutable_path))
            _, chapter_count = get_epub_word_and_chapter_count(current_path)

            db_book.title = metadata["title"]
            db_book.author = metadata["author"]
            db_book.series = metadata["series"]
            db_book.immutable_path = str(immutable_path.relative_to(LIBRARY_PATH.parent))
            db_book.current_path = str(current_path.relative_to(LIBRARY_PATH.parent))
            db_book.master_word_count = master_word_count
            db_book.current_word_count = master_word_count

            cover_path = get_and_save_epub_cover(epub_path=immutable_path, book_id=db_book.id)
            if cover_path is None:
                cover_path = await scrape_cover(source_url, db_book.id)
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


async def update_web_novels() -> None:
    """Scheduler job: checks all web novels for updates every 24 hours."""
    logger.info("Starting web novel update job.")
    db = SessionLocal()
    task = None
    failed = False
    try:
        books = await crud.get_web_books(db)
        task = await crud.get_active_update_task(db)
        if not task:
            task = await crud.create_update_task(db, total_books=len(books))
        logger.info(f"Update task {task.id} processing {task.completed_books}/{task.total_books} books.")

        for book in books:
            latest_log = await crud.get_latest_book_log(db, book.id)
            if latest_log and latest_log.timestamp >= task.started_at:
                logger.info(f"Skipping {book.title}, already processed in this task.")
                continue
            logger.info(f"Checking {book.title} for updates.")
            try:
                immutable_path = LIBRARY_PATH.parent / book.immutable_path
                current_path = LIBRARY_PATH.parent / book.current_path

                old_word_count, old_chapter_count = get_epub_word_and_chapter_count(immutable_path)
                result = await download_web_novel(book.source_url)

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
                    await crud.increment_update_task(db, task)
                    continue

                new_epub_path, _ = result
                new_epub_path.rename(immutable_path)
                with open(immutable_path, "rb") as f_in, open(current_path, "wb") as f_out:
                    f_out.write(f_in.read())

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
                await crud.increment_update_task(db, task)
            except Exception as e:
                logger.error(f"Failed to update {book.title}: {e}\n{traceback.format_exc()}")
    except Exception as e:
        logger.error(f"Scheduler run failed: {e}\n{traceback.format_exc()}")
        failed = True
    finally:
        if task is not None:
            if failed:
                await crud.fail_update_task(db, task)
            else:
                await crud.complete_update_task(db, task)
        await db.close()
