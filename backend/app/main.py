import asyncio
import collections
import re
import traceback
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, status, Depends, UploadFile, File, BackgroundTasks, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
import logging
from typing import List, Dict, Any, Optional
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import zipfile
from lxml import etree
import requests as http_requests

from pydantic import BaseModel

from . import crud, models, schemas, epub_editor
from .database import engine, get_db, SessionLocal
from fanficfare.cli import main as fff_main


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# In-memory log buffer (most-recent 1000 records)
_LOG_BUFFER: collections.deque = collections.deque(maxlen=1000)


class _MemoryLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _LOG_BUFFER.append(
            {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
            }
        )


_mem_handler = _MemoryLogHandler()
_mem_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(_mem_handler)


def _get_epub_word_and_chapter_count(epub_path: Path) -> tuple[int, int]:
    """
    Calculates the word and chapter count of an EPUB file.
    """
    try:
        book = epub.read_epub(epub_path)
        chapters = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
        word_count = 0
        for chapter in chapters:
            soup = BeautifulSoup(chapter.get_content(), "html.parser")
            text = soup.get_text()
            word_count += len(text.split())
        return word_count, len(chapters)
    except Exception as e:
        logger.error(f"Error reading epub file {epub_path}: {e}")
        return 0, 0


def _run_fff_main(args: List[str]) -> int:
    """
    Wrapper for fff_main to handle SystemExit and return a status code.
    """
    try:
        fff_main(args)
        return 0  # Assume success if no exception
    except SystemExit as e:
        return e.code if e.code is not None else 0
    except Exception as e:
        logger.error(f"An unexpected error occurred in FanFicFare: {e}")
        return 1


async def _download_and_parse_web_novel(source_url: str, overwrite: bool = False) -> Optional[tuple[Path, Dict[str, Any]]]:
    """
    Downloads a web novel using FanFicFare and parses its metadata.
    Returns the path to the EPUB and the metadata dictionary, or None if FFF
    determined the story has not been updated (only possible when overwrite=False).
    Set overwrite=True (for refresh/manual) to force FFF to re-download
    even when the local file is newer than the story's last update date.
    """
    app_dir = Path(__file__).parent.resolve()
    ini_path = app_dir / "personal.ini"
    library_path = (app_dir / ".." / ".." / "library").resolve()
    library_path.mkdir(exist_ok=True)

    if not ini_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error: personal.ini not found.",
        )

    async with asyncio.Lock():
        before_epubs = {f: f.stat().st_mtime for f in library_path.iterdir() if f.suffix == ".epub"}
        args = [
            "-c",
            str(ini_path),
            "-o",
            f"output_dir={str(library_path)}",
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
            for f in library_path.iterdir()
            if f.suffix == ".epub" and (f not in before_epubs or f.stat().st_mtime > before_epubs[f])
        ]

    if not changed_epubs:
        if not overwrite:
            # FFF skipped the download because the story hasn't been updated — normal outcome
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
        metadata = {"title": title, "author": author, "series": series}
        return new_epub_path, metadata
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse EPUB metadata: {e}",
        )


async def _save_cover_from_url(url: str, book_id: int, library_path: Path) -> Optional[Path]:
    """
    Downloads an image from a URL and saves it as the cover for the given book.
    Returns the saved Path on success, or None on failure.
    """
    covers_path = (library_path / "covers").resolve()
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


async def _try_scrape_cover(source_url: str, book_id: int, library_path: Path) -> Optional[Path]:
    """
    Attempts to scrape a cover image from a known site's book page.
    Currently supports Royal Road.
    """
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
        return await _save_cover_from_url(img["src"], book_id, library_path)
    except Exception as e:
        logger.error(f"Failed to scrape cover from {source_url}: {e}")
        return None


async def _finish_web_novel_download(book_id: int, source_url: str) -> None:
    """
    Background task: downloads the actual EPUB for a pending book, then updates the record.
    """
    async with SessionLocal() as db:
        db_book = await crud.get_book(db, book_id=book_id)
        if db_book is None:
            logger.error(f"Background download: book {book_id} not found")
            return

        library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()

        chapter_count = 0
        master_word_count = 0
        try:
            result = await _download_and_parse_web_novel(source_url)
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

            immutable_path = library_path / f"immutable_{new_epub_path.name}"
            current_path = library_path / new_epub_path.name
            new_epub_path.rename(immutable_path)
            with open(immutable_path, "rb") as f_in, open(current_path, "wb") as f_out:
                f_out.write(f_in.read())

            master_word_count = epub_editor.get_word_count(str(immutable_path))
            _, chapter_count = _get_epub_word_and_chapter_count(current_path)

            db_book.title = metadata["title"]
            db_book.author = metadata["author"]
            db_book.series = metadata["series"]
            db_book.immutable_path = str(immutable_path.relative_to(library_path.parent))
            db_book.current_path = str(current_path.relative_to(library_path.parent))
            db_book.master_word_count = master_word_count
            db_book.current_word_count = master_word_count
            cover_path_or_none = _get_and_save_epub_cover(epub_path=immutable_path, book_id=db_book.id)
            if cover_path_or_none is None:
                cover_path_or_none = await _try_scrape_cover(source_url, db_book.id, library_path)
            if cover_path_or_none:
                db_book.cover_path = str(cover_path_or_none.relative_to(library_path.parent))
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

        # Post-commit steps: run only after a successful commit so that a
        # failure here cannot overwrite the already-persisted success state.
        log_entry = schemas.BookLogCreate(
            book_id=db_book.id,
            entry_type="added",
            new_chapter_count=chapter_count,
            words_added=master_word_count,
        )
        await crud.create_book_log(db, log_entry)
        await db.refresh(db_book)
        await epub_editor.apply_book_cleaning(db_book, db)


# Create all database tables on startup
async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


scheduler = AsyncIOScheduler()


async def update_web_novels():
    """
    Job to update all web novels.
    """
    logger.info("Starting web novel update job.")
    db: AsyncSession = SessionLocal()
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
                library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()
                immutable_path = library_path.parent / book.immutable_path
                current_path = library_path.parent / book.current_path

                old_word_count, old_chapter_count = _get_epub_word_and_chapter_count(immutable_path)

                result = await _download_and_parse_web_novel(book.source_url)

                if result is None:
                    # FFF confirmed no update since last download
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

                # Mirror refresh_book: overwrite immutable with fresh download, copy to current
                new_epub_path.rename(immutable_path)
                with open(immutable_path, "rb") as f_in, open(current_path, "wb") as f_out:
                    f_out.write(f_in.read())

                new_word_count, new_chapter_count = _get_epub_word_and_chapter_count(immutable_path)

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Re-attach memory handler after uvicorn resets logging config on startup
    root_logger = logging.getLogger()
    if _mem_handler not in root_logger.handlers:
        root_logger.addHandler(_mem_handler)
    logger.info("Starting up and creating database tables if they don't exist.")
    await create_tables()
    async with SessionLocal() as db:
        await crud.reset_stuck_update_tasks(db)
    scheduler.add_job(update_web_novels, "interval", hours=24)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Story Manager", lifespan=lifespan)


class WebNovelRequest(BaseModel):
    url: schemas.HttpUrl


class EpubUploadResult(BaseModel):
    filename: str
    status: str  # "success" | "skipped" | "error"
    book: Optional[schemas.Book] = None
    error: Optional[str] = None


def detect_series_from_titles(titles: list[str]) -> dict[str, str]:
    """
    Given a list of book titles, detect which ones belong to a series.

    Pass 1 — numbered anchors: looks for "<series> <number|roman> [- <subtitle>]".
    A series prefix is confirmed only when 2+ numbered entries share it.

    Pass 2 — unnumbered members: for each confirmed prefix, also matches:
      - a title that IS exactly the prefix  (e.g. "12 Miles Below")
      - a title that starts with the prefix + ": " or " - "
        (e.g. "12 Miles Below: A Prog Fantasy")
    """
    _ROMAN = re.compile(
        r'^M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$',
        re.IGNORECASE,
    )
    _TITLE_RE = re.compile(r'^(.+?)\s+(\d+|[IVXLCDMivxlcdm]+)(?:\s*[-:]\s*.+)?$')

    # Pass 1: collect (normalized_key, original_prefix) for numbered titles
    parsed: dict[str, tuple[str, str]] = {}
    for title in titles:
        m = _TITLE_RE.match(title.strip())
        if not m:
            continue
        prefix, num = m.group(1).strip(), m.group(2)
        if not num.isdigit() and not _ROMAN.match(num):
            continue
        parsed[title] = (prefix.lower(), prefix)

    groups: dict[str, dict] = {}
    for title, (key, prefix) in parsed.items():
        if key not in groups:
            groups[key] = {"prefix": prefix, "titles": []}
        groups[key]["titles"].append(title)

    result: dict[str, str] = {}
    confirmed: dict[str, str] = {}  # normalized_key -> canonical prefix
    for key, group in groups.items():
        if len(group["titles"]) >= 2:
            for title in group["titles"]:
                result[title] = group["prefix"]
            confirmed[key] = group["prefix"]

    # Pass 2: pull in unnumbered titles that match a confirmed prefix
    for title in titles:
        if title in result:
            continue
        t = title.strip().lower()
        for key, prefix in confirmed.items():
            if t == key or t.startswith(key + ": ") or t.startswith(key + " - "):
                result[title] = prefix
                break

    return result


async def _upload_epub_file(
    file: UploadFile, library_path: Path, db: AsyncSession
) -> models.Book:
    """
    Saves an EPUB file to the library, extracts metadata, creates a DB record,
    saves the cover, logs the addition, and applies cleaning. Raises HTTPException
    on duplicate or parse errors.
    """
    immutable_path = library_path / f"immutable_{file.filename}"
    with open(immutable_path, "wb+") as f:
        f.write(file.file.read())

    current_path = library_path / file.filename
    with open(current_path, "wb+") as f:
        file.file.seek(0)
        f.write(file.file.read())

    try:
        epub_book = epub.read_epub(immutable_path)
        title = epub_book.get_metadata("DC", "title")[0][0]
        author = epub_book.get_metadata("DC", "creator")[0][0]
    except Exception as e:
        immutable_path.unlink(missing_ok=True)
        current_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse EPUB file: {e}",
        )

    existing = await crud.get_book_by_title_and_author(db, title=title, author=author)
    if existing:
        immutable_path.unlink(missing_ok=True)
        current_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A book with title '{title}' by '{author}' already exists (id={existing.id})",
        )

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
            source_url = dc_source[0][0]
            source_type = models.SourceType.web
            logger.info(f"Detected FFF epub with source URL: {source_url}")
    except Exception as e:
        logger.warning(f"Failed to parse dc:source metadata: {e}")

    master_word_count = epub_editor.get_word_count(str(immutable_path))

    book_to_create = schemas.BookCreate(
        title=title,
        author=author,
        series=series,
        immutable_path=str(immutable_path.relative_to(library_path.parent)),
        current_path=str(current_path.relative_to(library_path.parent)),
        source_url=source_url,
        source_type=source_type,
        master_word_count=master_word_count,
        current_word_count=master_word_count,
    )

    db_book = await crud.create_book(db=db, book=book_to_create)

    cover_path_or_none = _get_and_save_epub_cover(epub_path=immutable_path, book_id=db_book.id)
    if cover_path_or_none:
        db_book.cover_path = str(cover_path_or_none.relative_to(library_path.parent))
        await db.commit()
        await db.refresh(db_book)

    _, chapter_count = _get_epub_word_and_chapter_count(current_path)
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


@app.post(
    "/api/books/upload_epub",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.Book,
)
async def upload_epub(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)) -> models.Book:
    """
    Uploads a single EPUB file, extracts metadata, and adds it to the database.
    """
    app_dir = Path(__file__).parent.resolve()
    library_path = (app_dir / ".." / ".." / "library").resolve()
    library_path.mkdir(exist_ok=True)
    return await _upload_epub_file(file, library_path, db)


@app.post("/api/books/upload_epubs", response_model=List[EpubUploadResult])
async def upload_epubs(
    files: List[UploadFile] = File(...), db: AsyncSession = Depends(get_db)
) -> List[EpubUploadResult]:
    """
    Uploads multiple EPUB files. After processing all files, auto-detects series
    groupings among books that have no series metadata, using the pattern
    "<series name> <number> [- <subtitle>]".
    """
    app_dir = Path(__file__).parent.resolve()
    library_path = (app_dir / ".." / ".." / "library").resolve()
    library_path.mkdir(exist_ok=True)

    results: List[EpubUploadResult] = []
    created_books: List[models.Book] = []

    for file in files:
        try:
            db_book = await _upload_epub_file(file, library_path, db)
            results.append(EpubUploadResult(filename=file.filename, status="success", book=db_book))
            created_books.append(db_book)
        except HTTPException as e:
            status_str = "skipped" if e.status_code == 409 else "error"
            results.append(EpubUploadResult(filename=file.filename, status=status_str, error=e.detail))
        except Exception as e:
            results.append(EpubUploadResult(filename=file.filename, status="error", error=str(e)))

    # Detect series across the uploaded batch AND existing library books without a series.
    # This handles the case where book 1 was already in the library and book 2 is being uploaded now.
    batch_ids = {b.id for b in created_books}
    batch_no_series = [b for b in created_books if not b.series]
    existing_no_series = [b for b in await crud.get_books_without_series(db) if b.id not in batch_ids]
    all_candidates = batch_no_series + existing_no_series

    if len(all_candidates) >= 2:
        series_map = detect_series_from_titles([b.title for b in all_candidates])
        updated = [b for b in all_candidates if b.title in series_map]
        if updated:
            for b in updated:
                b.series = series_map[b.title]
            await db.commit()
            for b in updated:
                await db.refresh(b)
            logger.info(
                f"Auto-detected series for {len(updated)} books: "
                + ", ".join(f"'{b.title}' → '{b.series}'" for b in updated)
            )

    return results


@app.post("/api/books/detect-series")
async def detect_series_in_library(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Scans all books in the library that have no series assigned and auto-detects
    series groupings using title patterns like "<series> <number> [- <subtitle>]".
    Only books without an existing series are considered or updated.
    """
    candidates = await crud.get_books_without_series(db)
    if len(candidates) < 2:
        return {"updated": 0, "series_detected": []}

    series_map = detect_series_from_titles([b.title for b in candidates])
    to_update = [b for b in candidates if b.title in series_map]

    if not to_update:
        return {"updated": 0, "series_detected": []}

    for b in to_update:
        b.series = series_map[b.title]
    await db.commit()

    series_detected = sorted(set(series_map.values()))
    logger.info(f"detect-series: updated {len(to_update)} books, series: {series_detected}")
    return {"updated": len(to_update), "series_detected": series_detected}


@app.post(
    "/api/books/add_web_novel",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.Book,
)
async def add_web_novel(
    request: WebNovelRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> models.Book:
    """
    Immediately creates a pending book record and downloads the web novel in the background.
    """
    source_url_str = str(request.url)

    # Check if the book already exists
    existing_book = await crud.get_book_by_source_url(db, source_url=source_url_str)
    if existing_book:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Book from URL {source_url_str} already exists in the library.",
        )

    # Create a placeholder record immediately so the UI can show progress
    book_to_create = schemas.BookCreate(
        title=source_url_str,
        author="Pending",
        source_url=request.url,
        source_type=models.SourceType.web,
        download_status="pending",
    )
    db_book = await crud.create_book(db=db, book=book_to_create)

    background_tasks.add_task(_finish_web_novel_download, db_book.id, source_url_str)

    return db_book


@app.get("/api/books", response_model=List[schemas.Book])
async def get_all_books(
    skip: int = 0,
    limit: int = 100,
    sort_by: str = "title",
    sort_order: str = "asc",
    db: AsyncSession = Depends(get_db),
) -> List[schemas.Book]:
    """
    Retrieve a list of all books in the library.
    """
    books = await crud.get_books(db, skip=skip, limit=limit, sort_by=sort_by, sort_order=sort_order)
    return [schemas.Book.from_orm(book) for book in books]


@app.get("/api/books/search", response_model=List[schemas.Book])
async def search_books_unified(
    q: str,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> List[schemas.Book]:
    """
    Search books by title, author, or series.
    """
    books = await crud.search_books(db, q=q, skip=skip, limit=limit)
    return books


@app.get("/api/books/search/author/{author}", response_model=List[schemas.Book])
async def search_books_by_author(
    author: str, skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)
) -> List[models.Book]:
    """
    Search for books by author.
    """
    books = await crud.get_books_by_author(db, author=author, skip=skip, limit=limit)
    return books


@app.get("/api/books/search/series/{series}", response_model=List[schemas.Book])
async def search_books_by_series(
    series: str, skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)
) -> List[models.Book]:
    """
    Search for books by series.
    """
    books = await crud.get_books_by_series(db, series=series, skip=skip, limit=limit)
    return books


@app.post("/api/books/reprocess-all", response_model=Dict[str, int])
async def reprocess_all_books(db: AsyncSession = Depends(get_db)):
    books = await crud.get_books(db, limit=10000)
    for book in books:
        await epub_editor.apply_book_cleaning(book, db, force=True)
    return {"reprocessed": len(books)}


@app.get("/api/books/count")
async def count_books_endpoint(q: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    total = await crud.count_books(db, q=q)
    return {"total": total}


@app.get("/api/logs")
async def get_logs(limit: int = 200, level: Optional[str] = None):
    entries = list(_LOG_BUFFER)
    if level:
        upper = level.upper()
        entries = [e for e in entries if e["level"] == upper]
    return entries[-limit:]


@app.post("/api/storage/cleanup")
async def cleanup_storage(dry_run: bool = True, db: AsyncSession = Depends(get_db)):
    """
    Scans the library directory for files not referenced by any book record.
    dry_run=True (default): returns what would be deleted without deleting anything.
    dry_run=False: deletes the orphaned files and returns what was deleted.
    """
    library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()
    if not library_path.exists():
        return {"dry_run": dry_run, "files": [], "total_bytes": 0}

    # Collect all paths tracked by the DB (relative to library_path.parent, same as stored)
    books = await crud.get_books(db, limit=100000)
    tracked: set[str] = set()
    for book in books:
        if book.immutable_path:
            tracked.add(str((library_path.parent / book.immutable_path).resolve()))
        if book.current_path:
            tracked.add(str((library_path.parent / book.current_path).resolve()))
        if book.cover_path:
            tracked.add(str((library_path.parent / book.cover_path).resolve()))

    orphans = []
    for file in library_path.rglob("*"):
        if not file.is_file():
            continue
        path_str = str(file.resolve())
        if path_str not in tracked:
            size = file.stat().st_size
            orphans.append({"path": str(file.relative_to(library_path.parent)), "size_bytes": size})

    total_bytes = sum(f["size_bytes"] for f in orphans)

    if not dry_run:
        for f in orphans:
            full = library_path.parent / f["path"]
            full.unlink(missing_ok=True)
        logger.info(f"Storage cleanup: deleted {len(orphans)} orphaned files ({total_bytes} bytes)")

    return {"dry_run": dry_run, "files": orphans, "total_bytes": total_bytes}


@app.get("/api/scheduler/status", response_model=Optional[schemas.UpdateTask])
async def get_scheduler_status(db: AsyncSession = Depends(get_db)):
    return await crud.get_latest_update_task(db)


@app.post("/api/scheduler/trigger", status_code=202)
async def trigger_scheduler(background_tasks: BackgroundTasks):
    background_tasks.add_task(update_web_novels)
    return {"message": "Update triggered"}


@app.get("/api/scheduler/history", response_model=List[schemas.UpdateTask])
async def get_scheduler_history(limit: int = 20, offset: int = 0, db: AsyncSession = Depends(get_db)):
    return await crud.get_update_tasks(db, limit=limit, offset=offset)


@app.get("/api/scheduler/history/{task_id}/logs", response_model=List[schemas.BookLogWithTitle])
async def get_task_logs(task_id: int, db: AsyncSession = Depends(get_db)):
    task, rows = await crud.get_book_logs_for_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return [
        schemas.BookLogWithTitle(
            id=log.id,
            book_id=log.book_id,
            book_title=title,
            entry_type=log.entry_type,
            previous_chapter_count=log.previous_chapter_count,
            new_chapter_count=log.new_chapter_count,
            words_added=log.words_added,
            timestamp=log.timestamp,
        )
        for log, title in rows
    ]


@app.put("/api/books/{book_id}", response_model=schemas.Book)
async def update_book_details(
    book_id: int, book_update: schemas.BookUpdate, db: AsyncSession = Depends(get_db)
) -> models.Book:
    """
    Update a book's details.
    """
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    update_dict = book_update.model_dump(exclude_unset=True)
    updated_book = await crud.update_book(db=db, book=db_book, update_data=book_update)
    if "content_selectors" in update_dict or "removed_chapters" in update_dict:
        await epub_editor.apply_book_cleaning(updated_book, db)
    return updated_book


@app.post("/api/books/{book_id}/refresh", response_model=schemas.Book)
async def refresh_book(book_id: int, db: AsyncSession = Depends(get_db)) -> models.Book:
    """
    Refreshes a book's metadata from its source URL.
    """
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    if not db_book.source_url:
        raise HTTPException(status_code=400, detail="Book does not have a source URL to refresh from.")

    library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()
    immutable_path = library_path.parent / db_book.immutable_path
    current_path = library_path.parent / db_book.current_path

    old_word_count, old_chapter_count = _get_epub_word_and_chapter_count(current_path)

    new_epub_path, metadata = await _download_and_parse_web_novel(db_book.source_url, overwrite=True)

    # The new download becomes the new immutable, and we copy it to current
    new_epub_path.rename(immutable_path)
    with open(immutable_path, "rb") as f_in, open(current_path, "wb") as f_out:
        f_out.write(f_in.read())

    new_word_count, new_chapter_count = _get_epub_word_and_chapter_count(current_path)

    if new_chapter_count > old_chapter_count:
        logger.info(f"Found {new_chapter_count - old_chapter_count} new chapters for {db_book.title}.")
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
    await db.commit()
    await db.refresh(updated_book)

    await epub_editor.apply_book_cleaning(updated_book, db)

    return updated_book


@app.get("/api/books/{book_id}/chapters", response_model=List[Dict[str, Any]])
async def get_book_chapters(book_id: int, db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if not db_book.immutable_path:
        raise HTTPException(status_code=404, detail="EPUB file not found")

    library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()
    # Always get chapters from the original immutable epub
    epub_path = library_path.parent / db_book.immutable_path

    if not epub_path.exists():
        raise HTTPException(status_code=404, detail="EPUB file not found")

    return epub_editor.get_chapters(str(epub_path))


@app.get("/api/books/{book_id}/download")
async def download_book(book_id: int, db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()
    current_path = library_path.parent / db_book.current_path
    if not current_path.is_file():
        raise HTTPException(status_code=404, detail="EPUB file not found")
    filename = Path(db_book.current_path).name
    return FileResponse(
        current_path,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/books/{book_id}/process", response_model=schemas.Book)
async def process_book_endpoint(book_id: int, db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    await epub_editor.apply_book_cleaning(db_book, db, force=True)

    return db_book


class PreviewCleaningRequest(BaseModel):
    content_selectors: List[str] = []
    removed_chapters: List[str] = []


@app.post("/api/books/{book_id}/preview-cleaning")
async def preview_cleaning(book_id: int, req: PreviewCleaningRequest, db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    configs = []
    if db_book.source_url:
        configs = await crud.get_all_matching_cleaning_configs(db, str(db_book.source_url))
    chapter_selectors, config_content_selectors = [], []
    for cfg in configs:
        chapter_selectors += list(cfg.chapter_selectors or [])
        config_content_selectors += list(cfg.content_selectors or [])
    all_content_selectors = config_content_selectors + req.content_selectors
    library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()
    immutable_path = library_path.parent / db_book.immutable_path
    return epub_editor.preview_epub(str(immutable_path), req.removed_chapters, all_content_selectors, chapter_selectors)


@app.get("/api/books/{book_id}/matched-config", response_model=List[schemas.CleaningConfig])
async def get_book_matched_config(book_id: int, db: AsyncSession = Depends(get_db)):
    """
    Returns all CleaningConfigs that match the book's source URL.
    """
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if not db_book.source_url:
        return []
    configs = await crud.get_all_matching_cleaning_configs(db, str(db_book.source_url))
    return configs


@app.delete("/api/books/by-title/{title}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book_by_title(title: str, db: AsyncSession = Depends(get_db)):
    """
    Deletes a book by its title.
    """
    book = await crud.get_book_by_title(db, title=title)
    if book is None:
        # Return 204 even if the book doesn't exist to make the endpoint idempotent
        return None

    library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()
    if book.immutable_path:
        immutable_path = library_path.parent / book.immutable_path
        if immutable_path.exists():
            immutable_path.unlink()
    if book.current_path:
        current_path = library_path.parent / book.current_path
        if current_path.exists():
            current_path.unlink()

    await crud.delete_book(db, book=book)
    return None


@app.delete("/api/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book_by_id(book_id: int, db: AsyncSession = Depends(get_db)):
    """
    Deletes a book by its ID.
    """
    book = await crud.get_book(db, book_id=book_id)
    if book is None:
        return None

    library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()
    if book.immutable_path:
        immutable_path = library_path.parent / book.immutable_path
        if immutable_path.exists():
            immutable_path.unlink()
    if book.current_path:
        current_path = library_path.parent / book.current_path
        if current_path.exists():
            current_path.unlink()

    await crud.delete_book(db, book=book)
    return None


@app.post("/api/cleaning-configs", status_code=status.HTTP_201_CREATED, response_model=schemas.CleaningConfig)
async def create_cleaning_config_endpoint(
    config: schemas.CleaningConfigCreate, db: AsyncSession = Depends(get_db)
) -> models.CleaningConfig:
    return await crud.create_cleaning_config(db, config)


@app.get("/api/cleaning-configs", response_model=List[schemas.CleaningConfig])
async def list_cleaning_configs(db: AsyncSession = Depends(get_db)) -> List[models.CleaningConfig]:
    return await crud.get_cleaning_configs(db)


@app.get("/api/cleaning-configs/{config_id}", response_model=schemas.CleaningConfig)
async def get_cleaning_config_endpoint(config_id: int, db: AsyncSession = Depends(get_db)) -> models.CleaningConfig:
    config = await crud.get_cleaning_config(db, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Cleaning config not found")
    return config


@app.put("/api/cleaning-configs/{config_id}", response_model=schemas.CleaningConfig)
async def update_cleaning_config_endpoint(
    config_id: int,
    update: schemas.CleaningConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> models.CleaningConfig:
    config = await crud.get_cleaning_config(db, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Cleaning config not found")
    config = await crud.update_cleaning_config(db, config, update)
    books = await crud.get_web_books(db)
    for book in books:
        if book.source_url and re.search(config.url_pattern, str(book.source_url)):
            await epub_editor.apply_book_cleaning(book, db)
    return config


@app.delete("/api/cleaning-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cleaning_config_endpoint(config_id: int, db: AsyncSession = Depends(get_db)) -> None:
    config = await crud.get_cleaning_config(db, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Cleaning config not found")
    await crud.delete_cleaning_config(db, config)
    return None


@app.get("/")
def read_root() -> Dict[str, str]:
    return {"message": "Welcome to the Story Manager API"}


@app.get("/api/covers/{book_id}")
async def get_cover_image(book_id: int, db: AsyncSession = Depends(get_db)):
    """
    Serves the cover image for a given book ID.
    """
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None or not db_book.cover_path:
        raise HTTPException(status_code=404, detail="Cover not found")

    library_path = (Path(__file__).parent.resolve() / ".." / "..").resolve()
    cover_path = library_path / db_book.cover_path

    if not cover_path.is_file():
        raise HTTPException(status_code=404, detail="Cover file not found")

    return FileResponse(cover_path)


@app.post("/api/books/{book_id}/cover", response_model=schemas.Book)
async def upload_book_cover(book_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    app_dir = Path(__file__).parent.resolve()
    covers_path = (app_dir / ".." / ".." / "library" / "covers").resolve()
    covers_path.mkdir(exist_ok=True)
    ext = Path(file.filename).suffix or ".jpg"
    save_path = covers_path / f"{book_id}{ext}"
    with open(save_path, "wb") as f:
        f.write(await file.read())
    library_path = (app_dir / ".." / ".." / "library").resolve()
    db_book.cover_path = str(save_path.relative_to(library_path.parent))
    await db.commit()
    await db.refresh(db_book)
    return db_book


class CoverUrlRequest(BaseModel):
    url: str


@app.post("/api/books/{book_id}/cover-url", response_model=schemas.Book)
async def set_cover_from_url(book_id: int, req: CoverUrlRequest, db: AsyncSession = Depends(get_db)):
    """
    Downloads an image from a URL and sets it as the book's cover.
    """
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    app_dir = Path(__file__).parent.resolve()
    library_path = (app_dir / ".." / ".." / "library").resolve()

    save_path = await _save_cover_from_url(req.url, book_id, library_path)
    if save_path is None:
        raise HTTPException(status_code=400, detail="Failed to download image from the provided URL")

    db_book.cover_path = str(save_path.relative_to(library_path.parent))
    await db.commit()
    await db.refresh(db_book)
    return db_book


# ---------------------------------------------------------------------------
# OPDS catalog
# ---------------------------------------------------------------------------

_ATOM_NS = "http://www.w3.org/2005/Atom"
_OPDS_NS = "http://opds-spec.org/2010/catalog"

ET.register_namespace("", _ATOM_NS)
ET.register_namespace("opds", _OPDS_NS)
ET.register_namespace("dcterms", "http://purl.org/dc/terms/")


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_book_entry(book, base_url: str) -> ET.Element:
    entry = ET.Element(f"{{{_ATOM_NS}}}entry")
    ET.SubElement(entry, f"{{{_ATOM_NS}}}id").text = f"urn:story-manager:book:{book.id}"
    ET.SubElement(entry, f"{{{_ATOM_NS}}}title").text = book.title
    author_el = ET.SubElement(entry, f"{{{_ATOM_NS}}}author")
    ET.SubElement(author_el, f"{{{_ATOM_NS}}}name").text = book.author
    ET.SubElement(entry, f"{{{_ATOM_NS}}}updated").text = (
        book.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ") if book.updated_at else _now_utc()
    )
    acq_link = ET.SubElement(entry, f"{{{_ATOM_NS}}}link")
    acq_link.set("rel", "http://opds-spec.org/acquisition")
    acq_link.set("href", f"{base_url}/api/books/{book.id}/download")
    acq_link.set("type", "application/epub+zip")
    if book.cover_path:
        img_link = ET.SubElement(entry, f"{{{_ATOM_NS}}}link")
        img_link.set("rel", "http://opds-spec.org/image")
        img_link.set("href", f"{base_url}/api/covers/{book.id}")
        img_link.set("type", "image/jpeg")
    if book.notes:
        ET.SubElement(entry, f"{{{_ATOM_NS}}}summary").text = book.notes
    return entry


def _opds_xml(feed: ET.Element) -> str:
    return '<?xml version="1.0" encoding="utf-8"?>' + ET.tostring(feed, encoding="unicode")


@app.get("/opds")
async def opds_root(request: Request):
    base_url = str(request.base_url).rstrip("/")
    nav_type = "application/atom+xml;profile=opds-catalog;kind=navigation"
    acq_type = "application/atom+xml;profile=opds-catalog;kind=acquisition"

    feed = ET.Element(f"{{{_ATOM_NS}}}feed")
    ET.SubElement(feed, f"{{{_ATOM_NS}}}id").text = "urn:story-manager:root"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}title").text = "Story Manager Library"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}updated").text = _now_utc()

    for rel, href, ftype in [
        ("self", f"{base_url}/opds", nav_type),
        ("start", f"{base_url}/opds", nav_type),
        ("search", f"{base_url}/opds/search?q={{searchTerms}}", "application/atom+xml"),
    ]:
        link = ET.SubElement(feed, f"{{{_ATOM_NS}}}link")
        link.set("rel", rel)
        link.set("href", href)
        link.set("type", ftype)

    entry = ET.SubElement(feed, f"{{{_ATOM_NS}}}entry")
    ET.SubElement(entry, f"{{{_ATOM_NS}}}id").text = "urn:story-manager:catalog"
    ET.SubElement(entry, f"{{{_ATOM_NS}}}title").text = "All Books"
    ET.SubElement(entry, f"{{{_ATOM_NS}}}updated").text = _now_utc()
    entry_link = ET.SubElement(entry, f"{{{_ATOM_NS}}}link")
    entry_link.set("rel", "subsection")
    entry_link.set("href", f"{base_url}/opds/catalog")
    entry_link.set("type", acq_type)

    return Response(content=_opds_xml(feed), media_type="application/atom+xml; charset=utf-8")


@app.get("/opds/catalog")
async def opds_catalog(request: Request, page: int = 0, page_size: int = 20, db: AsyncSession = Depends(get_db)):
    base_url = str(request.base_url).rstrip("/")
    books = await crud.get_books(db, skip=page * page_size, limit=page_size)
    acq_type = "application/atom+xml;profile=opds-catalog;kind=acquisition"
    nav_type = "application/atom+xml;profile=opds-catalog;kind=navigation"

    feed = ET.Element(f"{{{_ATOM_NS}}}feed")
    ET.SubElement(feed, f"{{{_ATOM_NS}}}id").text = "urn:story-manager:catalog"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}title").text = "All Books"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}updated").text = _now_utc()

    self_link = ET.SubElement(feed, f"{{{_ATOM_NS}}}link")
    self_link.set("rel", "self")
    self_link.set("href", f"{base_url}/opds/catalog?page={page}&page_size={page_size}")
    self_link.set("type", acq_type)

    start_link = ET.SubElement(feed, f"{{{_ATOM_NS}}}link")
    start_link.set("rel", "start")
    start_link.set("href", f"{base_url}/opds")
    start_link.set("type", nav_type)

    if page > 0:
        prev_link = ET.SubElement(feed, f"{{{_ATOM_NS}}}link")
        prev_link.set("rel", "previous")
        prev_link.set("href", f"{base_url}/opds/catalog?page={page - 1}&page_size={page_size}")
        prev_link.set("type", acq_type)

    if len(books) == page_size:
        next_link = ET.SubElement(feed, f"{{{_ATOM_NS}}}link")
        next_link.set("rel", "next")
        next_link.set("href", f"{base_url}/opds/catalog?page={page + 1}&page_size={page_size}")
        next_link.set("type", acq_type)

    for book in books:
        feed.append(_build_book_entry(book, base_url))

    return Response(content=_opds_xml(feed), media_type="application/atom+xml; charset=utf-8")


@app.get("/opds/search")
async def opds_search(request: Request, q: str = "", db: AsyncSession = Depends(get_db)):
    base_url = str(request.base_url).rstrip("/")
    books = await crud.search_books(db, q=q, skip=0, limit=100)
    acq_type = "application/atom+xml;profile=opds-catalog;kind=acquisition"
    nav_type = "application/atom+xml;profile=opds-catalog;kind=navigation"

    feed = ET.Element(f"{{{_ATOM_NS}}}feed")
    ET.SubElement(feed, f"{{{_ATOM_NS}}}id").text = "urn:story-manager:search"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}title").text = f"Search: {q}"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}updated").text = _now_utc()

    self_link = ET.SubElement(feed, f"{{{_ATOM_NS}}}link")
    self_link.set("rel", "self")
    self_link.set("href", f"{base_url}/opds/search?q={q}")
    self_link.set("type", acq_type)

    start_link = ET.SubElement(feed, f"{{{_ATOM_NS}}}link")
    start_link.set("rel", "start")
    start_link.set("href", f"{base_url}/opds")
    start_link.set("type", nav_type)

    for book in books:
        feed.append(_build_book_entry(book, base_url))

    return Response(content=_opds_xml(feed), media_type="application/atom+xml; charset=utf-8")


def _get_and_save_epub_cover(epub_path: Path, book_id: int) -> Path | None:
    """
    Extracts the cover image from an EPUB file and saves it to the covers directory.
    """
    app_dir = Path(__file__).parent.resolve()
    covers_path = (app_dir / ".." / ".." / "library" / "covers").resolve()
    covers_path.mkdir(exist_ok=True)

    try:
        with zipfile.ZipFile(epub_path) as z:
            t = etree.fromstring(z.read("META-INF/container.xml"))
            rootfile_path = t.xpath(
                "/u:container/u:rootfiles/u:rootfile",
                namespaces={"u": "urn:oasis:names:tc:opendocument:xmlns:container"},
            )[0].get("full-path")

            t = etree.fromstring(z.read(rootfile_path))
            cover_id = t.xpath(
                "//opf:metadata/opf:meta[@name='cover']",
                namespaces={"opf": "http://www.idpf.org/2007/opf"},
            )[
                0
            ].get("content")

            cover_href = t.xpath(
                "//opf:manifest/opf:item[@id='" + cover_id + "']",
                namespaces={"opf": "http://www.idpf.org/2007/opf"},
            )[0].get("href")

            cover_path_in_epub = (Path(rootfile_path).parent / cover_href).as_posix()
            cover_data = z.read(cover_path_in_epub)
            cover_extension = Path(cover_href).suffix
            cover_filename = f"{book_id}{cover_extension}"
            save_path = covers_path / cover_filename

            with open(save_path, "wb") as f:
                f.write(cover_data)
            return save_path
    except Exception as e:
        logger.error(f"Error extracting cover from {epub_path}: {e}")
        return None
