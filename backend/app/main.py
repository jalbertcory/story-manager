import asyncio
from fastapi import FastAPI, HTTPException, status, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
import configparser
import logging
from typing import List, Dict, Any
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from pydantic import BaseModel

from . import crud, models, schemas, epub_editor
from .cleaning import clean_epub
from .database import engine, get_db, SessionLocal
from fanficfare.cli import main as fff_main


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


async def _download_and_parse_web_novel(source_url: str) -> tuple[Path, Dict[str, Any]]:
    """
    Downloads a web novel using FanFicFare and parses its metadata.
    Returns the path to the EPUB and the metadata dictionary.
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
        files_before = set(library_path.iterdir())
        args = [
            "--personal-ini",
            str(ini_path),
            "--output-dir",
            str(library_path),
            source_url,
        ]
        result = fff_main(args)
        if result != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"FanFicFare failed to download story. Error code: {result}.",
            )
        files_after = set(library_path.iterdir())
        new_files = files_after - files_before

    new_epub_files = [f for f in new_files if f.suffix == ".epub"]
    if not new_epub_files:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FanFicFare ran but no new EPUB file was created.",
        )
    new_epub_path = new_epub_files[0]

    metadata_path = new_epub_path.with_suffix(".fff_metadata")
    if not metadata_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Metadata file not found for {new_epub_path.name}",
        )

    config = configparser.ConfigParser()
    config.read(metadata_path)
    try:
        title = config.get("metadata", "title")
        author = config.get("metadata", "author")
        series = config.get("metadata", "series", fallback=None)
        metadata = {"title": title, "author": author, "series": series}
        return new_epub_path, metadata
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse metadata file: {e}",
        )


# Create all database tables on startup
async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


app = FastAPI(title="Story Manager")

scheduler = AsyncIOScheduler()


async def update_web_novels():
    """
    Job to update all web novels.
    """
    logger.info("Starting web novel update job.")
    db: AsyncSession = SessionLocal()
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
                epub_path = library_path.parent / book.epub_path

                old_word_count, old_chapter_count = _get_epub_word_and_chapter_count(epub_path)

                _, _ = await _download_and_parse_web_novel(book.source_url)

                new_word_count, new_chapter_count = _get_epub_word_and_chapter_count(epub_path)

                if new_chapter_count > old_chapter_count:
                    logger.info(f"Found {new_chapter_count - old_chapter_count} new chapters for {book.title}.")
                    log_entry = schemas.BookLogCreate(
                        book_id=book.id,
                        entry_type="updated",
                        previous_chapter_count=old_chapter_count,
                        new_chapter_count=new_chapter_count,
                        words_added=new_word_count - old_word_count,
                    )
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
                await crud.increment_update_task(db, task)
            except Exception as e:
                logger.error(f"Failed to update {book.title}: {e}")
        await crud.complete_update_task(db, task)
    finally:
        await db.close()


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Starting up and creating database tables if they don't exist.")
    await create_tables()
    scheduler.add_job(update_web_novels, "interval", days=7)
    scheduler.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    scheduler.shutdown()


class WebNovelRequest(BaseModel):
    url: schemas.HttpUrl


@app.post(
    "/api/books/upload_epub",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.Book,
)
async def upload_epub(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)) -> models.Book:
    """
    Uploads an EPUB file, extracts metadata, and adds it to the database.
    """
    app_dir = Path(__file__).parent.resolve()
    library_path = (app_dir / ".." / ".." / "library").resolve()
    library_path.mkdir(exist_ok=True)

    # Sanitize filename and save the file
    immutable_path = library_path / f"immutable_{file.filename}"
    with open(immutable_path, "wb+") as file_object:
        file_object.write(file.file.read())

    current_path = library_path / file.filename
    with open(current_path, "wb+") as file_object:
        file.file.seek(0)
        file_object.write(file.file.read())

    # Extract metadata from the EPUB file
    try:
        book = epub.read_epub(immutable_path)
        title = book.get_metadata("DC", "title")[0][0]
        author = book.get_metadata("DC", "creator")[0][0]

        series_metadata = book.get_metadata("calibre", "series")
        series = series_metadata[0][0] if series_metadata else None

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse EPUB file: {e}",
        )

    master_word_count = epub_editor.get_word_count(str(immutable_path))

    # Create the book record in the database
    book_to_create = schemas.BookCreate(
        title=title,
        author=author,
        immutable_path=str(immutable_path.relative_to(library_path.parent)),
        current_path=str(current_path.relative_to(library_path.parent)),
        series=series,
        source_type=models.SourceType.epub,
        master_word_count=master_word_count,
        current_word_count=master_word_count,
    )

    db_book = await crud.create_book(db=db, book=book_to_create)

    # Create a log entry for the new book
    _, chapter_count = _get_epub_word_and_chapter_count(current_path)
    log_entry = schemas.BookLogCreate(
        book_id=db_book.id,
        entry_type="added",
        new_chapter_count=chapter_count,
        words_added=master_word_count,
    )
    await crud.create_book_log(db, log_entry)

    return db_book


@app.post(
    "/api/books/add_web_novel",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.Book,
)
async def add_web_novel(request: WebNovelRequest, db: AsyncSession = Depends(get_db)) -> models.Book:
    """
    Downloads a web novel, saves it as an EPUB, and adds its metadata to the database.
    """
    source_url_str = str(request.url)

    # Check if the book already exists
    existing_book = await crud.get_book_by_source_url(db, source_url=source_url_str)
    if existing_book:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Book from URL {source_url_str} already exists in the library.",
        )

    # Download and parse the web novel
    new_epub_path, metadata = await _download_and_parse_web_novel(source_url_str)
    library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()

    # Create immutable and current copies
    immutable_path = library_path / f"immutable_{new_epub_path.name}"
    current_path = library_path / new_epub_path.name
    new_epub_path.rename(immutable_path)
    with open(immutable_path, "rb") as f_in, open(current_path, "wb") as f_out:
        f_out.write(f_in.read())

    master_word_count = epub_editor.get_word_count(str(immutable_path))

    # Create the book record in the database
    book_to_create = schemas.BookCreate(
        title=metadata["title"],
        author=metadata["author"],
        source_url=request.url,
        immutable_path=str(immutable_path.relative_to(library_path.parent)),
        current_path=str(current_path.relative_to(library_path.parent)),
        series=metadata["series"],
        source_type=models.SourceType.web,
        master_word_count=master_word_count,
        current_word_count=master_word_count,
    )

    db_book = await crud.create_book(db=db, book=book_to_create)

    # Create a log entry for the new book
    _, chapter_count = _get_epub_word_and_chapter_count(current_path)
    log_entry = schemas.BookLogCreate(
        book_id=db_book.id,
        entry_type="added",
        new_chapter_count=chapter_count,
        words_added=master_word_count,
    )
    await crud.create_book_log(db, log_entry)

    config = await crud.get_matching_cleaning_config(db, source_url_str)
    if config:
        clean_epub(current_path, config)

    return db_book


@app.get("/api/books", response_model=List[schemas.Book])
async def get_all_books(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)) -> List[models.Book]:
    """
    Retrieve a list of all books in the library.
    """
    books = await crud.get_books(db, skip=skip, limit=limit)
    return books


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
    updated_book = await crud.update_book(db=db, book=db_book, update_data=book_update)
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

    new_epub_path, metadata = await _download_and_parse_web_novel(db_book.source_url)

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

    # Reset processing state
    updated_book.removed_chapters = []
    updated_book.div_selectors = []
    updated_book.master_word_count = new_word_count
    updated_book.current_word_count = new_word_count
    await db.commit()
    await db.refresh(updated_book)

    config = await crud.get_matching_cleaning_config(db, str(db_book.source_url))
    if config:
        clean_epub(current_path, config)

    return updated_book


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
    return await crud.update_cleaning_config(db, config, update)


@app.delete("/api/cleaning-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cleaning_config_endpoint(config_id: int, db: AsyncSession = Depends(get_db)) -> None:
    config = await crud.get_cleaning_config(db, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Cleaning config not found")
    await crud.delete_cleaning_config(db, config)
    return None


@app.get("/api/books/{book_id}/chapters", response_model=List[Dict[str, Any]])
async def get_book_chapters(book_id: int, db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()
    # Always get chapters from the original immutable epub
    epub_path = library_path.parent / db_book.immutable_path

    if not epub_path.exists():
        raise HTTPException(status_code=404, detail="EPUB file not found")

    return epub_editor.get_chapters(str(epub_path))


@app.post("/api/books/{book_id}/process", response_model=schemas.Book)
async def process_book_endpoint(book_id: int, db: AsyncSession = Depends(get_db)):
    db_book = await crud.get_book(db, book_id=book_id)
    if db_book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()
    immutable_path = library_path.parent / db_book.immutable_path
    current_path = library_path.parent / db_book.current_path

    epub_editor.process_epub(
        str(immutable_path),
        str(current_path),
        db_book.removed_chapters,
        db_book.div_selectors,
    )

    new_word_count = epub_editor.get_word_count(str(current_path))
    db_book.current_word_count = new_word_count
    await db.commit()
    await db.refresh(db_book)

    return db_book


@app.get("/")
def read_root() -> Dict[str, str]:
    return {"message": "Welcome to the Story Manager API"}
