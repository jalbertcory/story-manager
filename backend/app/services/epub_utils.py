"""Lightweight EPUB helpers: word/chapter counting and cover extraction."""

import logging
import posixpath
import zipfile
from pathlib import Path, PurePosixPath
from typing import Optional
from urllib.parse import unquote

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub
from lxml import etree

logger = logging.getLogger(__name__)

OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
CONTAINER_NS = {"u": "urn:oasis:names:tc:opendocument:xmlns:container"}
DC_NS = {
    **OPF_NS,
    "dc": "http://purl.org/dc/elements/1.1/",
}

IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
IMAGE_EXTENSION_BY_MEDIA_TYPE = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}
SYNTHETIC_SUBJECTS = {"Completed", "In-Progress", "Unknown"}
SYNTHETIC_SUBJECT_PREFIXES = ("Last Update:", "Last Update Year/Month:")
SCRIBBLEHUB_GENRES = {
    "Action",
    "Adult",
    "Adventure",
    "Boys Love",
    "Comedy",
    "Drama",
    "Ecchi",
    "Fanfiction",
    "Fantasy",
    "Gender Bender",
    "Girls Love",
    "Harem",
    "Historical",
    "Horror",
    "Isekai",
    "Josei",
    "LitRPG",
    "Martial Arts",
    "Mature",
    "Mecha",
    "Mystery",
    "Psychological",
    "Romance",
    "School Life",
    "Sci-fi",
    "Seinen",
    "Shoujo",
    "Shounen",
    "Slice of Life",
    "Smut",
    "Sports",
    "Supernatural",
    "Tragedy",
    "Wuxia",
    "Xianxia",
    "Yaoi",
    "Yuri",
}


def get_epub_word_and_chapter_count(epub_path: Path) -> tuple[int, int]:
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


def _read_rootfile_path(archive: zipfile.ZipFile) -> Optional[str]:
    container = etree.fromstring(archive.read("META-INF/container.xml"))
    rootfiles = container.xpath(
        "/u:container/u:rootfiles/u:rootfile",
        namespaces=CONTAINER_NS,
    )
    if not rootfiles:
        return None
    return rootfiles[0].get("full-path")


def _resolve_epub_href(base_path: str, href: str | None) -> Optional[str]:
    if not href:
        return None

    clean_href = unquote(href.split("#", 1)[0]).strip()
    if not clean_href:
        return None
    if clean_href.startswith("/"):
        return posixpath.normpath(clean_href.lstrip("/"))

    return posixpath.normpath(posixpath.join(posixpath.dirname(base_path), clean_href))


def _is_image_path(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in IMAGE_EXTENSIONS


def _is_image_item(item: etree._Element) -> bool:
    return (item.get("media-type") or "").lower().startswith("image/")


def _manifest_items(package: etree._Element) -> list[etree._Element]:
    return package.xpath("//opf:manifest/opf:item", namespaces=OPF_NS)


def _manifest_item_by_id(package: etree._Element, item_id: str | None) -> Optional[etree._Element]:
    if not item_id:
        return None
    return next((item for item in _manifest_items(package) if item.get("id") == item_id), None)


def _image_path_from_html(archive: zipfile.ZipFile, html_path: str) -> Optional[str]:
    try:
        soup = BeautifulSoup(archive.read(html_path), "html.parser")
    except KeyError:
        return None

    for image in soup.select("img[src], image[href], image[xlink\\:href]"):
        image_href = image.get("src") or image.get("href") or image.get("xlink:href")
        image_path = _resolve_epub_href(html_path, image_href)
        if image_path and image_path in archive.namelist() and _is_image_path(image_path):
            return image_path
    return None


def _cover_image_path_from_guide(
    archive: zipfile.ZipFile,
    rootfile_path: str,
    package: etree._Element,
) -> Optional[str]:
    guide_refs = package.xpath("//opf:guide/opf:reference[@type='cover']", namespaces=OPF_NS)
    for guide_ref in guide_refs:
        cover_path = _resolve_epub_href(rootfile_path, guide_ref.get("href"))
        if not cover_path or cover_path not in archive.namelist():
            continue
        if _is_image_path(cover_path):
            return cover_path
        html_cover_path = _image_path_from_html(archive, cover_path)
        if html_cover_path:
            return html_cover_path
    return None


def _find_cover_image_path(
    archive: zipfile.ZipFile,
    rootfile_path: str,
    package: etree._Element,
) -> Optional[tuple[str, Optional[str]]]:
    meta_cover = package.xpath("//opf:metadata/opf:meta[@name='cover']", namespaces=OPF_NS)
    for meta in meta_cover:
        item = _manifest_item_by_id(package, meta.get("content"))
        if item is not None and _is_image_item(item):
            cover_path = _resolve_epub_href(rootfile_path, item.get("href"))
            if cover_path and cover_path in archive.namelist():
                return cover_path, item.get("media-type")

    for item in _manifest_items(package):
        properties = (item.get("properties") or "").split()
        if "cover-image" in properties and _is_image_item(item):
            cover_path = _resolve_epub_href(rootfile_path, item.get("href"))
            if cover_path and cover_path in archive.namelist():
                return cover_path, item.get("media-type")

    guide_cover_path = _cover_image_path_from_guide(archive, rootfile_path, package)
    if guide_cover_path:
        return guide_cover_path, None

    for item in _manifest_items(package):
        coverish = f"{item.get('id') or ''} {item.get('href') or ''}".lower()
        if "cover" in coverish and _is_image_item(item):
            cover_path = _resolve_epub_href(rootfile_path, item.get("href"))
            if cover_path and cover_path in archive.namelist():
                return cover_path, item.get("media-type")

    image_items = [item for item in _manifest_items(package) if _is_image_item(item)]
    if len(image_items) == 1:
        cover_path = _resolve_epub_href(rootfile_path, image_items[0].get("href"))
        if cover_path and cover_path in archive.namelist():
            return cover_path, image_items[0].get("media-type")

    return None


def get_and_save_epub_cover(epub_path: Path, book_id: int) -> Optional[Path]:
    """Extracts the cover image from an EPUB file and saves it to the covers directory."""
    from ..config import LIBRARY_PATH

    covers_path = (LIBRARY_PATH / "covers").resolve()
    covers_path.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(epub_path) as z:
            rootfile_path = _read_rootfile_path(z)
            if not rootfile_path:
                logger.info("No EPUB rootfile found in %s.", epub_path)
                return None

            package = etree.fromstring(z.read(rootfile_path))
            cover_match = _find_cover_image_path(z, rootfile_path, package)
            if not cover_match:
                logger.info("No embedded cover image found in %s.", epub_path)
                return None

            cover_path_in_epub, media_type = cover_match
            cover_data = z.read(cover_path_in_epub)
            cover_extension = PurePosixPath(cover_path_in_epub).suffix or IMAGE_EXTENSION_BY_MEDIA_TYPE.get(
                media_type or "", ".jpg"
            )
            save_path = covers_path / f"{book_id}{cover_extension}"

            with open(save_path, "wb") as f:
                f.write(cover_data)
            return save_path
    except Exception as e:
        logger.error(f"Error extracting cover from {epub_path}: {e}")
        return None


def _split_tag_values(raw_value: str) -> list[str]:
    return [tag.strip() for tag in raw_value.split(",") if tag.strip()]


def _dedupe_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for tag in tags:
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tag)
    return deduped


def _extract_title_page_tag_groups(html: bytes) -> dict[str, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    tag_groups = {"category": [], "genre": []}
    for label in soup.find_all(["b", "strong"]):
        label_text = label.get_text(" ", strip=True).rstrip(":").casefold()
        if label_text not in {"category", "genre"}:
            continue

        value_parts: list[str] = []
        for sibling in label.next_siblings:
            if getattr(sibling, "name", None) == "br":
                break
            if hasattr(sibling, "get_text"):
                value_parts.append(sibling.get_text(" ", strip=True))
            else:
                value_parts.append(str(sibling))
        tag_groups[label_text].extend(_split_tag_values(" ".join(value_parts)))

    return {key: _dedupe_tags(values) for key, values in tag_groups.items()}


def _extract_title_page_tag_metadata(
    archive: zipfile.ZipFile, rootfile_path: str, package: etree._Element
) -> dict[str, list[str]]:
    title_page_items = [
        item
        for item in _manifest_items(package)
        if item.get("media-type") == "application/xhtml+xml"
        and ("title" in (item.get("id") or "").casefold() or "title" in (item.get("href") or "").casefold())
    ]
    for item in title_page_items:
        title_page_path = _resolve_epub_href(rootfile_path, item.get("href"))
        if not title_page_path or title_page_path not in archive.namelist():
            continue
        tag_groups = _extract_title_page_tag_groups(archive.read(title_page_path))
        if tag_groups["category"] or tag_groups["genre"]:
            return {
                "genre_tags": tag_groups["genre"],
                "source_tags": tag_groups["category"],
            }
    return {"genre_tags": [], "source_tags": []}


def _extract_subject_tags(package: etree._Element) -> list[str]:
    tags: list[str] = []
    for subject in package.xpath("//opf:metadata/dc:subject", namespaces=DC_NS):
        value = (subject.text or "").strip()
        if not value or value in SYNTHETIC_SUBJECTS:
            continue
        if any(value.startswith(prefix) for prefix in SYNTHETIC_SUBJECT_PREFIXES):
            continue
        tags.append(value)
    return _dedupe_tags(tags)


def _is_scribblehub_package(package: etree._Element) -> bool:
    values = []
    for field in ("source", "publisher"):
        values.extend(
            (node.text or "").strip()
            for node in package.xpath(f"//opf:metadata/dc:{field}", namespaces=DC_NS)
            if (node.text or "").strip()
        )
    return any("scribblehub.com" in value.casefold() for value in values)


def _split_subject_tags(subject_tags: list[str]) -> dict[str, list[str]]:
    genre_lookup = {tag.casefold() for tag in SCRIBBLEHUB_GENRES}
    genre_tags = []
    source_tags = []
    for tag in subject_tags:
        if tag.casefold() in genre_lookup:
            genre_tags.append(tag)
        else:
            source_tags.append(tag)
    return {
        "genre_tags": _dedupe_tags(genre_tags),
        "source_tags": _dedupe_tags(source_tags),
    }


def get_epub_tag_metadata(epub_path: Path) -> dict[str, list[str]]:
    """Return broad genres and source-specific tags from an EPUB."""
    try:
        with zipfile.ZipFile(epub_path) as z:
            rootfile_path = _read_rootfile_path(z)
            if not rootfile_path:
                return {"genre_tags": [], "source_tags": []}
            package = etree.fromstring(z.read(rootfile_path))

            title_page_tags = _extract_title_page_tag_metadata(z, rootfile_path, package)
            if title_page_tags["genre_tags"] or title_page_tags["source_tags"]:
                return title_page_tags

            subject_tags = _extract_subject_tags(package)
            if _is_scribblehub_package(package):
                return _split_subject_tags(subject_tags)
            return {"genre_tags": subject_tags, "source_tags": []}
    except Exception as e:
        logger.warning(f"Error extracting genre tags from {epub_path}: {e}")
        return {"genre_tags": [], "source_tags": []}


def get_epub_genre_tags(epub_path: Path) -> list[str]:
    """Return broad genre tags from an EPUB."""
    return get_epub_tag_metadata(epub_path)["genre_tags"]


def get_epub_source_tags(epub_path: Path) -> list[str]:
    """Return source-site category/tag metadata from an EPUB."""
    return get_epub_tag_metadata(epub_path)["source_tags"]
