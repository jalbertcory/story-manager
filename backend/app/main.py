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


from pydantic import BaseModel, HttpUrl

from . import crud, models, schemas
from .database import engine, get_db
from fanficfare.cli import main as fff_main

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create all database tables on startup
async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)

app = FastAPI(title="Story Manager")

@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Starting up and creating database tables if they don't exist.")
    await create_tables()

class WebNovelRequest(BaseModel):
    url: schemas.HttpUrl


@app.post("/api/books/upload_epub", status_code=status.HTTP_201_CREATED, response_model=schemas.Book)
async def upload_epub(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)) -> models.Book:
    """
    Uploads an EPUB file, extracts metadata, and adds it to the database.
    """
    app_dir = Path(__file__).parent.resolve()
    library_path = (app_dir / ".." / ".." / "library").resolve()
    library_path.mkdir(exist_ok=True)

    # Sanitize filename and save the file
    file_location = library_path / file.filename
    with open(file_location, "wb+") as file_object:
        file_object.write(file.file.read())

    # Extract metadata from the EPUB file
    try:
        book = epub.read_epub(file_location)
        title = book.get_metadata('DC', 'title')[0][0]
        author = book.get_metadata('DC', 'creator')[0][0]

        series_metadata = book.get_metadata('calibre', 'series')
        series = series_metadata[0][0] if series_metadata else None

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse EPUB file: {e}",
        )

    # Create the book record in the database
    book_to_create = schemas.BookCreate(
        title=title,
        author=author,
        epub_path=str(file_location.relative_to(library_path.parent)),
        series=series,
    )

    db_book = await crud.create_book(db=db, book=book_to_create)
    return db_book


@app.post("/api/books/add_web_novel", status_code=status.HTTP_201_CREATED, response_model=schemas.Book)
async def add_web_novel(request: WebNovelRequest, db: AsyncSession = Depends(get_db)) -> models.Book:
    """
    Downloads a web novel, saves it as an EPUB, and adds its metadata to the database.
    """
    source_url_str = str(request.url)

    # 1. Check if the book already exists in the database
    existing_book = await crud.get_book_by_source_url(db, source_url=source_url_str)
    if existing_book:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Book from URL {source_url_str} already exists in the library.",
        )

    app_dir = Path(__file__).parent.resolve()
    ini_path = app_dir / "personal.ini"
    library_path = (app_dir / ".." / ".." / "library").resolve()
    library_path.mkdir(exist_ok=True)

    if not ini_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error: personal.ini not found."
        )

    # 2. Download the book using FanFicFare
    # We'll use a lock to prevent race conditions when multiple requests come in
    # and we're trying to identify the newly created file.
    async with asyncio.Lock():
        files_before = set(library_path.iterdir())

        args = ["--personal-ini", str(ini_path), "--output-dir", str(library_path), source_url_str]
        result = fff_main(args)

        if result != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"FanFicFare failed to download story. Error code: {result}.",
            )

        files_after = set(library_path.iterdir())
        new_files = files_after - files_before

    new_epub_files = [f for f in new_files if f.suffix == '.epub']
    if not new_epub_files:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FanFicFare ran but no new EPUB file was created.",
        )
    new_epub_path = new_epub_files[0]

    # 3. Read metadata from the .fff_metadata file
    metadata_path = new_epub_path.with_suffix('.fff_metadata')
    if not metadata_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Metadata file not found for {new_epub_path.name}",
        )

    config = configparser.ConfigParser()
    config.read(metadata_path)

    try:
        title = config.get('metadata', 'title')
        author = config.get('metadata', 'author')
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse metadata file: {e}",
        )

    # 4. Create the book record in the database
    series_info = config.get('metadata', 'series', fallback=None)
    book_to_create = schemas.BookCreate(
        title=title,
        author=author,
        source_url=request.url,
        epub_path=str(new_epub_path.relative_to(library_path.parent)), # Store relative path
        series=series_info,
    )

    db_book = await crud.create_book(db=db, book=book_to_create)
    return db_book


@app.get("/api/books", response_model=List[schemas.Book])
async def get_all_books(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)) -> List[models.Book]:
    """
    Retrieve a list of all books in the library.
    """
    books = await crud.get_books(db, skip=skip, limit=limit)
    return books


@app.get("/api/books/search/author/{author}", response_model=List[schemas.Book])
async def search_books_by_author(author: str, skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)) -> List[models.Book]:
    """
    Search for books by author.
    """
    books = await crud.get_books_by_author(db, author=author, skip=skip, limit=limit)
    return books


@app.get("/api/books/search/series/{series}", response_model=List[schemas.Book])
async def search_books_by_series(series: str, skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)) -> List[models.Book]:
    """
    Search for books by series.
    """
    books = await crud.get_books_by_series(db, series=series, skip=skip, limit=limit)
    return books


@app.get("/")
def read_root() -> Dict[str, str]:
    return {"message": "Welcome to the Story Manager API"}
