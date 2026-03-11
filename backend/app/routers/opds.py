"""OPDS catalog endpoints for e-reader client integration."""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

_ATOM_NS = "http://www.w3.org/2005/Atom"
_OPDS_NS = "http://opds-spec.org/2010/catalog"

ET.register_namespace("", _ATOM_NS)
ET.register_namespace("opds", _OPDS_NS)
ET.register_namespace("dcterms", "http://purl.org/dc/terms/")


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _opds_xml(feed: ET.Element) -> str:
    return '<?xml version="1.0" encoding="utf-8"?>' + ET.tostring(feed, encoding="unicode")


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


@router.get("/opds")
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


@router.get("/opds/catalog")
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


@router.get("/opds/search")
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
