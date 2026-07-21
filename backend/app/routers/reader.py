"""Authenticated, read-only reader API and OPDS endpoints."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..auth import get_reader_api_key
from ..config import LIBRARY_PATH
from ..database import get_db
from ..services.audiobook_publication import (
    chapter_reader_audio_path,
    chapter_reader_smil_bytes,
    normalize_resource_href,
    sha256_bytes,
    sha256_file,
    stable_chapter_key,
    text_reader_path,
)

router = APIRouter(dependencies=[Depends(get_reader_api_key)])

_ATOM_NS = "http://www.w3.org/2005/Atom"
_OPDS_NS = "http://opds-spec.org/2010/catalog"
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")

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

    if book.source_type == models.SourceType.web and book.source_url:
        source_link = ET.SubElement(entry, f"{{{_ATOM_NS}}}link")
        source_link.set("rel", "alternate")
        source_link.set("href", book.source_url)
        source_link.set("type", "text/html")

    if book.cover_path:
        img_link = ET.SubElement(entry, f"{{{_ATOM_NS}}}link")
        img_link.set("rel", "http://opds-spec.org/image")
        img_link.set("href", f"{base_url}/reader/covers/{book.id}")
        img_link.set("type", "image/jpeg")

    return entry


def _normalize_genre_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        cleaned = raw_tag.strip()
        if not cleaned:
            continue
        folded = cleaned.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        normalized.append(cleaned)
    return sorted(normalized, key=str.casefold)


def _effective_genre_tags(book: models.Book, series_user_genre_tags: list[str] | None = None) -> list[str]:
    return _normalize_genre_tags(
        [
            *(series_user_genre_tags or []),
            *(book.user_genre_tags or []),
            *(book.genre_tags or []),
        ]
    )


def _reader_book_payload(
    book: models.Book,
    request: Request,
    *,
    series_user_genre_tags: list[str] | None = None,
    audiobook_chapters: list[models.AudiobookChapter] | None = None,
) -> dict:
    base_url = str(request.base_url).rstrip("/")
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "series": book.series,
        "series_index": float(book.series_index) if book.series_index is not None else None,
        "source_url": book.source_url if book.source_type == models.SourceType.web else None,
        "source_type": book.source_type,
        "content_updated_at": book.content_updated_at,
        "content_version": book.content_version,
        "current_word_count": book.current_word_count,
        "effective_genre_tags": _effective_genre_tags(book, series_user_genre_tags),
        "download_url": f"{base_url}/reader/books/{book.id}/download",
        "cover_url": f"{base_url}/reader/covers/{book.id}" if book.cover_path else None,
        "audiobook": _reader_audiobook_capability(book, audiobook_chapters or []),
    }


def _reader_audiobook_status(book: models.Book, ready: int, total: int) -> str:
    if book.audiobook_publication_state in {"processing", "partial", "complete", "error"}:
        return book.audiobook_publication_state
    if book.audiobook_pipeline_status == "error":
        return "error"
    if total and ready == total and book.audiobook_pipeline_status == "complete":
        return "complete"
    return "partial" if ready else "processing"


def _reader_audiobook_capability(
    book: models.Book,
    chapters: list[models.AudiobookChapter],
) -> dict | None:
    if not book.audiobook_enabled:
        return None
    if not book.audiobook_pipeline_status and not book.audiobook_revision and not chapters:
        return None
    ready_chapters = [
        chapter
        for chapter in chapters
        if chapter.generation_state == "ready" and chapter_reader_audio_path(chapter) is not None
    ]
    ready_bytes = 0
    for chapter in ready_chapters:
        if chapter.audio_size_bytes is not None:
            ready_bytes += chapter.audio_size_bytes
            continue
        audio_path = chapter_reader_audio_path(chapter)
        if audio_path and audio_path.is_file():
            ready_bytes += audio_path.stat().st_size
    content_version = book.content_version or 1
    return {
        "status": _reader_audiobook_status(book, len(ready_chapters), len(chapters)),
        "revision": book.audiobook_revision or 0,
        "source_content_version": book.audiobook_source_content_version or content_version,
        "text_content_version": book.audiobook_text_content_version or content_version,
        "ready_chapter_count": len(ready_chapters),
        "total_chapter_count": len(chapters),
        "ready_audio_bytes": ready_bytes,
        "manifest_url": f"/reader/books/{book.id}/audiobook/manifest",
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
    series_names = [row["name"] for row in series_rows]

    metadata_map = await crud.get_series_metadata_for_names(db, series_names)
    needs_books = [n for n in series_names if n not in metadata_map]
    book_groups = await crud.get_reader_books_by_series_names(db, needs_books)

    results = []
    for row in series_rows:
        name = row["name"]
        meta = metadata_map.get(name)
        genre_tags = crud.compute_effective_series_genre_tags(book_groups.get(name, []), meta)
        results.append(
            schemas.ReaderSeriesSummary(
                name=name,
                book_count=row["book_count"],
                total_words=row["total_words"],
                latest_update=row["latest_update"],
                cover_url=f"{base_url}/reader/covers/{row['cover_book_id']}" if row.get("cover_book_id") else None,
                genre_tags=genre_tags,
            )
        )
    return results


async def _series_metadata_map(db: AsyncSession, books: list[models.Book]) -> dict[str, models.SeriesMetadata]:
    series_names = sorted({book.series for book in books if book.series})
    return await crud.get_series_metadata_for_names(db, series_names)


async def _reader_books_response(books: list[models.Book], request: Request, db: AsyncSession) -> list[schemas.ReaderBook]:
    metadata_map = await _series_metadata_map(db, books)
    chapters_by_book = await crud.audiobook.get_chapters_for_books(db, [book.id for book in books])
    return [
        schemas.ReaderBook.model_validate(
            _reader_book_payload(
                book,
                request,
                series_user_genre_tags=(
                    metadata_map[book.series].user_genre_tags if book.series and book.series in metadata_map else None
                ),
                audiobook_chapters=chapters_by_book.get(book.id, []),
            )
        )
        for book in books
    ]


@router.get("/reader/series/{series_name}/books", response_model=list[schemas.ReaderBook])
async def get_reader_series_books(
    series_name: str, request: Request, db: AsyncSession = Depends(get_db)
) -> list[schemas.ReaderBook]:
    books = await crud.get_reader_books_by_series(db, series_name)
    return await _reader_books_response(books, request, db)


@router.get("/reader/books/all", response_model=list[schemas.ReaderBook])
async def get_all_reader_books(request: Request, db: AsyncSession = Depends(get_db)) -> list[schemas.ReaderBook]:
    books = await crud.get_all_reader_books(db)
    return await _reader_books_response(books, request, db)


@router.get("/reader/books/standalone", response_model=list[schemas.ReaderBook])
async def get_reader_standalone_books(request: Request, db: AsyncSession = Depends(get_db)) -> list[schemas.ReaderBook]:
    books = await crud.get_reader_standalone_books(db)
    return await _reader_books_response(books, request, db)


@router.get("/reader/books/{book_id}", response_model=schemas.ReaderBook)
async def get_reader_book(book_id: int, request: Request, db: AsyncSession = Depends(get_db)) -> schemas.ReaderBook:
    book = await crud.get_reader_book(db, book_id)
    results = await _reader_books_response([book], request, db)
    return results[0]


@router.get("/reader/updates", response_model=list[schemas.ReaderBook])
async def get_reader_updates(
    request: Request,
    since: datetime | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[schemas.ReaderBook]:
    books = await crud.get_reader_updates(db, since)
    return await _reader_books_response(books, request, db)


async def _reader_audiobook_book(book_id: int, db: AsyncSession) -> models.Book:
    book = await crud.get_reader_book(db, book_id)
    if not book.audiobook_enabled or (not book.audiobook_pipeline_status and not book.audiobook_revision):
        raise HTTPException(status_code=404, detail="Generated audiobook is not available")
    return book


def _etag(value: str) -> str:
    return f'"{value}"'


def _etag_matches(request: Request, etag: str) -> bool:
    candidates = {value.strip().removeprefix("W/") for value in request.headers.get("if-none-match", "").split(",")}
    return "*" in candidates or etag in candidates


def _asset_headers(etag: str, size: int, *, ranges: bool = False) -> dict[str, str]:
    headers = {
        "ETag": etag,
        "Content-Length": str(size),
        "Cache-Control": "private, max-age=0, must-revalidate",
        "X-Content-Type-Options": "nosniff",
    }
    if ranges:
        headers["Accept-Ranges"] = "bytes"
    return headers


def _manifest_chapter(chapter: models.AudiobookChapter, book_id: int) -> dict:
    href = normalize_resource_href(chapter.source_href or chapter.content_file_name, chapter.chapter_number)
    key = chapter.stable_chapter_key or stable_chapter_key(href)
    audio_path = chapter_reader_audio_path(chapter)
    smil_content = chapter_reader_smil_bytes(chapter)
    is_ready = (
        chapter.generation_state == "ready"
        and audio_path is not None
        and audio_path.is_file()
        and smil_content is not None
        and (chapter.audio_revision or 0) > 0
    )
    state = chapter.generation_state if chapter.generation_state in {"pending", "processing", "error"} else "ready"
    payload = {
        "key": key,
        "title": chapter.title or f"Chapter {chapter.chapter_number}",
        "href": href,
        "state": "ready" if is_ready else state,
        "audio_version": None,
        "duration_ms": None,
        "audio_size_bytes": None,
        "audio_sha256": None,
        "smil_size_bytes": None,
        "smil_sha256": None,
        "audio_url": None,
        "smil_url": None,
    }
    if not is_ready:
        return payload
    version = chapter.audio_revision
    payload.update(
        {
            "audio_version": version,
            "duration_ms": chapter.duration_ms,
            "audio_size_bytes": chapter.audio_size_bytes or audio_path.stat().st_size,
            "audio_sha256": chapter.audio_sha256 or sha256_file(audio_path),
            "smil_size_bytes": chapter.smil_size_bytes or len(smil_content),
            "smil_sha256": chapter.smil_sha256 or sha256_bytes(smil_content),
            "audio_url": f"/reader/books/{book_id}/audiobook/chapters/{key}/audio?version={version}",
            "smil_url": f"/reader/books/{book_id}/audiobook/chapters/{key}/smil?version={version}",
        }
    )
    return payload


@router.get(
    "/reader/books/{book_id}/audiobook/manifest",
    response_model=schemas.ReaderAudiobookManifest,
)
async def reader_audiobook_manifest(
    book_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    book = await _reader_audiobook_book(book_id, db)
    text_path = text_reader_path(book)
    if text_path is None:
        raise HTTPException(status_code=404, detail="Audiobook text rendition is not available")
    chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    text_size = book.audiobook_text_size_bytes or text_path.stat().st_size
    text_sha = book.audiobook_text_sha256 or sha256_file(text_path)
    content_version = book.audiobook_text_content_version or book.content_version or 1
    manifest = {
        "revision": book.audiobook_revision or 0,
        "source_content_version": book.audiobook_source_content_version or book.content_version or 1,
        "text": {
            "content_version": content_version,
            "size_bytes": text_size,
            "sha256": text_sha,
            "url": f"/reader/books/{book_id}/audiobook/text",
        },
        "chapters": [_manifest_chapter(chapter, book_id) for chapter in chapters],
    }
    body = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
    etag = _etag(sha256_bytes(body))
    if _etag_matches(request, etag):
        return Response(status_code=304, headers={"ETag": etag})
    return Response(
        content=body,
        media_type="application/json",
        headers=_asset_headers(etag, len(body)),
    )


@router.get("/reader/books/{book_id}/audiobook/text")
async def reader_audiobook_text(
    book_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    book = await _reader_audiobook_book(book_id, db)
    path = text_reader_path(book)
    if path is None:
        raise HTTPException(status_code=404, detail="Audiobook text rendition is not available")
    sha = book.audiobook_text_sha256 or sha256_file(path)
    etag = _etag(sha)
    if _etag_matches(request, etag):
        return Response(status_code=304, headers={"ETag": etag})
    return FileResponse(
        path,
        media_type="application/epub+zip",
        headers=_asset_headers(etag, path.stat().st_size),
    )


def _stale_audiobook_revision(current_revision: int) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": "stale_audiobook_revision",
            "message": "Refresh the audiobook manifest before downloading this chapter.",
            "current_revision": current_revision,
        },
    )


async def _reader_audiobook_chapter(
    book_id: int,
    chapter_key: str,
    version: int,
    db: AsyncSession,
) -> models.AudiobookChapter | JSONResponse:
    await _reader_audiobook_book(book_id, db)
    chapter = await crud.audiobook.get_chapter_by_stable_key(db, book_id, chapter_key)
    if chapter is None or chapter.generation_state != "ready":
        raise HTTPException(status_code=404, detail="Audiobook chapter is not available")
    if version != chapter.audio_revision:
        return _stale_audiobook_revision(chapter.audio_revision or 0)
    return chapter


def _iter_file_range(path: Path, start: int, length: int) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as source:
        source.seek(start)
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/reader/books/{book_id}/audiobook/chapters/{chapter_key}/audio")
async def reader_audiobook_chapter_audio(
    book_id: int,
    chapter_key: str,
    version: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await _reader_audiobook_chapter(book_id, chapter_key, version, db)
    if isinstance(result, JSONResponse):
        return result
    path = chapter_reader_audio_path(result)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Audiobook audio file is not available")
    size = path.stat().st_size
    sha = result.audio_sha256 or sha256_file(path)
    etag = _etag(sha)
    if _etag_matches(request, etag):
        return Response(status_code=304, headers={"ETag": etag, "Accept-Ranges": "bytes"})
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(
            path,
            media_type="audio/mpeg",
            headers=_asset_headers(etag, size, ranges=True),
        )
    match = _RANGE_RE.fullmatch(range_header.strip())
    if not match:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
    first, last = match.groups()
    if not first and not last:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    else:
        suffix = int(last)
        if suffix <= 0:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
        start = max(0, size - suffix)
        end = size - 1
    if start >= size or end < start:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
    length = end - start + 1
    headers = _asset_headers(etag, length, ranges=True)
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        _iter_file_range(path, start, length),
        status_code=206,
        media_type="audio/mpeg",
        headers=headers,
    )


@router.get("/reader/books/{book_id}/audiobook/chapters/{chapter_key}/smil")
async def reader_audiobook_chapter_smil(
    book_id: int,
    chapter_key: str,
    version: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await _reader_audiobook_chapter(book_id, chapter_key, version, db)
    if isinstance(result, JSONResponse):
        return result
    content = chapter_reader_smil_bytes(result)
    if content is None:
        raise HTTPException(status_code=404, detail="Audiobook SMIL file is not available")
    sha = result.smil_sha256 or sha256_bytes(content)
    etag = _etag(sha)
    if _etag_matches(request, etag):
        return Response(status_code=304, headers={"ETag": etag})
    return Response(
        content=content,
        media_type="application/smil+xml",
        headers=_asset_headers(etag, len(content)),
    )


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
