"""Authenticated, read-only reader API and OPDS endpoints."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..auth import get_reader_api_key
from ..config import LIBRARY_PATH
from ..database import get_db

router = APIRouter(dependencies=[Depends(get_reader_api_key)])

_ATOM_NS = "http://www.w3.org/2005/Atom"
_OPDS_NS = "http://opds-spec.org/2010/catalog"

ET.register_namespace("", _ATOM_NS)
ET.register_namespace("opds", _OPDS_NS)
ET.register_namespace("dcterms", "http://purl.org/dc/terms/")


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _opds_xml(feed: ET.Element) -> str:
    return '<?xml version="1.0" encoding="utf-8"?>' + ET.tostring(feed, encoding="unicode")


def _book_updated(book: models.Book) -> str:
    updated = book.content_updated_at or book.updated_at
    if updated is None:
        return _now_utc()
    return updated.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _feed_link(feed: ET.Element, rel: str, href: str, type_: str) -> None:
    link = ET.SubElement(feed, f"{{{_ATOM_NS}}}link")
    link.set("rel", rel)
    link.set("href", href)
    link.set("type", type_)


def _build_book_entry(book: models.Book, base_url: str) -> ET.Element:
    entry = ET.Element(f"{{{_ATOM_NS}}}entry")
    ET.SubElement(entry, f"{{{_ATOM_NS}}}id").text = f"urn:story-manager:reader-book:{book.id}"
    ET.SubElement(entry, f"{{{_ATOM_NS}}}title").text = book.title
    author_el = ET.SubElement(entry, f"{{{_ATOM_NS}}}author")
    ET.SubElement(author_el, f"{{{_ATOM_NS}}}name").text = book.author
    ET.SubElement(entry, f"{{{_ATOM_NS}}}updated").text = _book_updated(book)

    acq_link = ET.SubElement(entry, f"{{{_ATOM_NS}}}link")
    acq_link.set("rel", "http://opds-spec.org/acquisition")
    acq_link.set("href", f"{base_url}/reader/books/{book.id}/download")
    acq_link.set("type", "application/epub+zip")

    if book.cover_path:
        img_link = ET.SubElement(entry, f"{{{_ATOM_NS}}}link")
        img_link.set("rel", "http://opds-spec.org/image")
        img_link.set("href", f"{base_url}/reader/covers/{book.id}")
        img_link.set("type", "image/jpeg")

    return entry


def _reader_book_payload(book: models.Book, request: Request) -> dict:
    base_url = str(request.base_url).rstrip("/")
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "series": book.series,
        "source_type": book.source_type,
        "content_updated_at": book.content_updated_at,
        "content_version": book.content_version,
        "current_word_count": book.current_word_count,
        "download_url": f"{base_url}/reader/books/{book.id}/download",
        "cover_url": f"{base_url}/reader/covers/{book.id}" if book.cover_path else None,
    }


@router.get("/reader/opds")
async def reader_opds_root(request: Request) -> Response:
    base_url = str(request.base_url).rstrip("/")
    nav_type = "application/atom+xml;profile=opds-catalog;kind=navigation"
    acq_type = "application/atom+xml;profile=opds-catalog;kind=acquisition"

    feed = ET.Element(f"{{{_ATOM_NS}}}feed")
    ET.SubElement(feed, f"{{{_ATOM_NS}}}id").text = "urn:story-manager:reader-root"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}title").text = "Story Manager Reader"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}updated").text = _now_utc()
    _feed_link(feed, "self", f"{base_url}/reader/opds", nav_type)
    _feed_link(feed, "start", f"{base_url}/reader/opds", nav_type)
    _feed_link(feed, "search", f"{base_url}/reader/opds/search?q={{searchTerms}}", "application/atom+xml")

    entry = ET.SubElement(feed, f"{{{_ATOM_NS}}}entry")
    ET.SubElement(entry, f"{{{_ATOM_NS}}}id").text = "urn:story-manager:reader-catalog"
    ET.SubElement(entry, f"{{{_ATOM_NS}}}title").text = "All Books"
    ET.SubElement(entry, f"{{{_ATOM_NS}}}updated").text = _now_utc()
    subsection = ET.SubElement(entry, f"{{{_ATOM_NS}}}link")
    subsection.set("rel", "subsection")
    subsection.set("href", f"{base_url}/reader/opds/catalog")
    subsection.set("type", acq_type)

    series_entry = ET.SubElement(feed, f"{{{_ATOM_NS}}}entry")
    ET.SubElement(series_entry, f"{{{_ATOM_NS}}}id").text = "urn:story-manager:reader-series"
    ET.SubElement(series_entry, f"{{{_ATOM_NS}}}title").text = "Series"
    ET.SubElement(series_entry, f"{{{_ATOM_NS}}}updated").text = _now_utc()
    series_link = ET.SubElement(series_entry, f"{{{_ATOM_NS}}}link")
    series_link.set("rel", "subsection")
    series_link.set("href", f"{base_url}/reader/opds/series")
    series_link.set("type", nav_type)

    return Response(content=_opds_xml(feed), media_type="application/atom+xml; charset=utf-8")


@router.get("/reader/opds/catalog")
async def reader_opds_catalog(
    request: Request,
    page: int = 0,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
) -> Response:
    base_url = str(request.base_url).rstrip("/")
    books = await crud.get_reader_books(db, skip=page * page_size, limit=page_size)
    acq_type = "application/atom+xml;profile=opds-catalog;kind=acquisition"
    nav_type = "application/atom+xml;profile=opds-catalog;kind=navigation"

    feed = ET.Element(f"{{{_ATOM_NS}}}feed")
    ET.SubElement(feed, f"{{{_ATOM_NS}}}id").text = "urn:story-manager:reader-catalog"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}title").text = "All Books"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}updated").text = _now_utc()
    _feed_link(feed, "self", f"{base_url}/reader/opds/catalog?page={page}&page_size={page_size}", acq_type)
    _feed_link(feed, "start", f"{base_url}/reader/opds", nav_type)

    if page > 0:
        _feed_link(feed, "previous", f"{base_url}/reader/opds/catalog?page={page - 1}&page_size={page_size}", acq_type)
    if len(books) == page_size:
        _feed_link(feed, "next", f"{base_url}/reader/opds/catalog?page={page + 1}&page_size={page_size}", acq_type)

    for book in books:
        feed.append(_build_book_entry(book, base_url))

    return Response(content=_opds_xml(feed), media_type="application/atom+xml; charset=utf-8")


@router.get("/reader/opds/search")
async def reader_opds_search(request: Request, q: str = "", db: AsyncSession = Depends(get_db)) -> Response:
    base_url = str(request.base_url).rstrip("/")
    books = await crud.search_reader_books(db, q=q, skip=0, limit=100)
    acq_type = "application/atom+xml;profile=opds-catalog;kind=acquisition"
    nav_type = "application/atom+xml;profile=opds-catalog;kind=navigation"

    feed = ET.Element(f"{{{_ATOM_NS}}}feed")
    ET.SubElement(feed, f"{{{_ATOM_NS}}}id").text = "urn:story-manager:reader-search"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}title").text = f"Search: {q}"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}updated").text = _now_utc()
    _feed_link(feed, "self", f"{base_url}/reader/opds/search?q={q}", acq_type)
    _feed_link(feed, "start", f"{base_url}/reader/opds", nav_type)

    for book in books:
        feed.append(_build_book_entry(book, base_url))

    return Response(content=_opds_xml(feed), media_type="application/atom+xml; charset=utf-8")


@router.get("/reader/opds/series")
async def reader_opds_series(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    base_url = str(request.base_url).rstrip("/")
    nav_type = "application/atom+xml;profile=opds-catalog;kind=navigation"
    acq_type = "application/atom+xml;profile=opds-catalog;kind=acquisition"

    feed = ET.Element(f"{{{_ATOM_NS}}}feed")
    ET.SubElement(feed, f"{{{_ATOM_NS}}}id").text = "urn:story-manager:reader-series"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}title").text = "Series"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}updated").text = _now_utc()
    _feed_link(feed, "self", f"{base_url}/reader/opds/series", nav_type)
    _feed_link(feed, "start", f"{base_url}/reader/opds", nav_type)

    series_rows = await crud.get_reader_series(db)
    for row in series_rows:
        entry = ET.SubElement(feed, f"{{{_ATOM_NS}}}entry")
        ET.SubElement(entry, f"{{{_ATOM_NS}}}id").text = f"urn:story-manager:reader-series:{row['name']}"
        ET.SubElement(entry, f"{{{_ATOM_NS}}}title").text = row["name"]
        ET.SubElement(entry, f"{{{_ATOM_NS}}}updated").text = _now_utc()
        link = ET.SubElement(entry, f"{{{_ATOM_NS}}}link")
        link.set("rel", "subsection")
        link.set("href", f"{base_url}/reader/opds/series/{quote(row['name'], safe='')}")
        link.set("type", acq_type)

    return Response(content=_opds_xml(feed), media_type="application/atom+xml; charset=utf-8")


@router.get("/reader/opds/series/{series_name}")
async def reader_opds_series_books(series_name: str, request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    base_url = str(request.base_url).rstrip("/")
    acq_type = "application/atom+xml;profile=opds-catalog;kind=acquisition"
    nav_type = "application/atom+xml;profile=opds-catalog;kind=navigation"
    series_path = quote(series_name, safe="")

    feed = ET.Element(f"{{{_ATOM_NS}}}feed")
    ET.SubElement(feed, f"{{{_ATOM_NS}}}id").text = f"urn:story-manager:reader-series:{series_name}"
    ET.SubElement(feed, f"{{{_ATOM_NS}}}title").text = series_name
    ET.SubElement(feed, f"{{{_ATOM_NS}}}updated").text = _now_utc()
    _feed_link(feed, "self", f"{base_url}/reader/opds/series/{series_path}", acq_type)
    _feed_link(feed, "start", f"{base_url}/reader/opds", nav_type)

    books = await crud.get_reader_books_by_series(db, series_name)
    for book in books:
        feed.append(_build_book_entry(book, base_url))

    return Response(content=_opds_xml(feed), media_type="application/atom+xml; charset=utf-8")


@router.get("/reader/series", response_model=list[schemas.ReaderSeriesSummary])
async def get_reader_series(request: Request, db: AsyncSession = Depends(get_db)) -> list[schemas.ReaderSeriesSummary]:
    base_url = str(request.base_url).rstrip("/")
    series_rows = await crud.get_reader_series(db)
    return [
        schemas.ReaderSeriesSummary(
            name=row["name"],
            book_count=row["book_count"],
            total_words=row["total_words"],
            latest_update=row["latest_update"],
            cover_url=f"{base_url}/reader/covers/{row['cover_book_id']}" if row.get("cover_book_id") else None,
        )
        for row in series_rows
    ]


@router.get("/reader/series/{series_name}/books", response_model=list[schemas.ReaderBook])
async def get_reader_series_books(
    series_name: str, request: Request, db: AsyncSession = Depends(get_db)
) -> list[schemas.ReaderBook]:
    books = await crud.get_reader_books_by_series(db, series_name)
    return [schemas.ReaderBook.model_validate(_reader_book_payload(book, request)) for book in books]


@router.get("/reader/books/{book_id}", response_model=schemas.ReaderBook)
async def get_reader_book(book_id: int, request: Request, db: AsyncSession = Depends(get_db)) -> schemas.ReaderBook:
    book = await crud.get_reader_book(db, book_id)
    return schemas.ReaderBook.model_validate(_reader_book_payload(book, request))


@router.get("/reader/updates", response_model=list[schemas.ReaderBook])
async def get_reader_updates(
    request: Request,
    since: datetime | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[schemas.ReaderBook]:
    books = await crud.get_reader_updates(db, since)
    return [schemas.ReaderBook.model_validate(_reader_book_payload(book, request)) for book in books]


@router.get("/reader/books/{book_id}/download")
async def reader_download_book(book_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    book = await crud.get_reader_book(db, book_id)
    current_path = LIBRARY_PATH.parent / book.current_path
    if not current_path.is_file():
        raise HTTPException(status_code=404, detail="EPUB file not found")
    return FileResponse(
        current_path,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{current_path.name}"'},
    )


@router.get("/reader/covers/{book_id}")
async def reader_cover(book_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    book = await crud.get_reader_book(db, book_id)
    if not book.cover_path:
        raise HTTPException(status_code=404, detail="Cover not found")
    cover_path = LIBRARY_PATH.parent / book.cover_path
    if not cover_path.is_file():
        raise HTTPException(status_code=404, detail="Cover file not found")
    return FileResponse(cover_path)
