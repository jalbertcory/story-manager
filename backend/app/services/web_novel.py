"""Web novel download pipeline: FanFicFare integration, background tasks, and the 24h update job."""

import asyncio
import copy
import logging
import shutil
import tempfile
import traceback
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ebooklib import epub
from fastapi import HTTPException, status
from lxml import etree

from .. import crud, epub_editor, models, schemas
from ..config import LIBRARY_PATH
from ..database import SessionLocal
from ..lifecycle import (
    AUDIOBOOK_PIPELINE,
    WEB_IMPORT,
    WEB_REFRESH,
    AudiobookPipelineStatus,
    WebImportStatus,
    WebRefreshStatus,
    transition_state,
)
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


class LosslessChapterUpdateError(RuntimeError):
    """Raised when an EPUB update cannot prove that it preserved every chapter."""


@dataclass(frozen=True)
class _LosslessChapterMerge:
    chapters: List[Dict[str, Any]]
    existing_ids: frozenset[str]
    remote_ids: frozenset[str]
    historical_ids: frozenset[str]
    new_ids: frozenset[str]


@dataclass(frozen=True)
class _LosslessUpdateResult:
    changed: bool
    preserved_chapter_count: int
    new_chapter_count: int


def _canonical_chapter_id(normalize_url: Callable[[str], str], url: str) -> str:
    canonical = normalize_url(url)
    return (canonical or url).strip()


def _build_lossless_chapter_merge(
    existing_urls: Sequence[str],
    existing_data: Mapping[str, Mapping[str, Any]],
    remote_chapters: Sequence[Mapping[str, Any]],
    normalize_url: Callable[[str], str],
) -> _LosslessChapterMerge:
    """Return an ordered URL union that never drops chapters from the EPUB.

    The source order is authoritative for chapters that are still online. Old-only
    chapters are inserted before their next shared source chapter, or immediately
    after the final shared chapter when the source has appended newer chapters.
    """

    existing_by_id: Dict[str, str] = {}
    for url in existing_urls:
        chapter_id = _canonical_chapter_id(normalize_url, url)
        if chapter_id in existing_by_id:
            raise LosslessChapterUpdateError(f"Existing EPUB has duplicate chapter identity: {chapter_id}")
        existing_by_id[chapter_id] = url

    remote_by_id: Dict[str, Mapping[str, Any]] = {}
    for chapter in remote_chapters:
        url = str(chapter.get("url") or "").strip()
        if not url:
            raise LosslessChapterUpdateError("Source returned a chapter without a URL.")
        chapter_id = _canonical_chapter_id(normalize_url, url)
        if chapter_id in remote_by_id:
            raise LosslessChapterUpdateError(f"Source has duplicate chapter identity: {chapter_id}")
        remote_by_id[chapter_id] = chapter

    existing_ids = frozenset(existing_by_id)
    remote_ids = frozenset(remote_by_id)
    shared_ids = existing_ids & remote_ids
    if existing_ids and remote_ids and not shared_ids:
        raise LosslessChapterUpdateError(
            "Existing EPUB and source have no chapters in common; refusing to combine potentially unrelated stories."
        )

    historical_ids = existing_ids - remote_ids
    new_ids = remote_ids - existing_ids

    def historical_chapter(chapter_id: str, index: int) -> Dict[str, Any]:
        url = existing_by_id[chapter_id]
        metadata = existing_data.get(url, {})
        title = metadata.get("chapterorigtitle") or metadata.get("chaptertitle") or f"Chapter {index + 1}"
        return {"title": str(title), "url": url}

    before_anchor: Dict[str, List[Dict[str, Any]]] = {}
    pending_historical: List[Dict[str, Any]] = []
    last_shared_id: Optional[str] = None
    for index, (chapter_id, _) in enumerate(existing_by_id.items()):
        if chapter_id in remote_ids:
            if pending_historical:
                before_anchor.setdefault(chapter_id, []).extend(pending_historical)
                pending_historical = []
            last_shared_id = chapter_id
        else:
            pending_historical.append(historical_chapter(chapter_id, index))

    trailing_historical = pending_historical
    merged: List[Dict[str, Any]] = []
    for chapter_id, chapter in remote_by_id.items():
        merged.extend(before_anchor.pop(chapter_id, []))
        merged.append(copy.deepcopy(dict(chapter)))
        if chapter_id == last_shared_id:
            merged.extend(trailing_historical)

    if before_anchor:
        raise LosslessChapterUpdateError("Could not place all historical chapters in the merged source order.")
    if trailing_historical and last_shared_id is None:
        merged = trailing_historical + merged

    merged_ids = [_canonical_chapter_id(normalize_url, str(chapter["url"])) for chapter in merged]
    expected_ids = existing_ids | remote_ids
    if len(merged_ids) != len(set(merged_ids)) or frozenset(merged_ids) != expected_ids:
        raise LosslessChapterUpdateError("Ordered chapter merge did not produce the complete unique URL union.")

    return _LosslessChapterMerge(
        chapters=merged,
        existing_ids=existing_ids,
        remote_ids=remote_ids,
        historical_ids=frozenset(historical_ids),
        new_ids=frozenset(new_ids),
    )


def _validate_lossless_epub(
    epub_path: Path,
    merge: _LosslessChapterMerge,
    normalize_url: Callable[[str], str],
) -> None:
    from fanficfare.epubutils import get_update_data

    update_data = get_update_data(epub_path)
    file_count = update_data[1]
    output_urls = list(update_data[7])
    output_ids = [_canonical_chapter_id(normalize_url, url) for url in output_urls]
    expected_ids = merge.existing_ids | merge.remote_ids

    if file_count != len(output_ids):
        raise LosslessChapterUpdateError(
            f"Updated EPUB has {file_count} chapter files but only {len(output_ids)} identifiable chapter URLs."
        )
    if len(output_ids) != len(set(output_ids)):
        raise LosslessChapterUpdateError("Updated EPUB contains duplicate chapter URLs.")
    if frozenset(output_ids) != expected_ids:
        missing_historical = len(merge.existing_ids - frozenset(output_ids))
        missing_remote = len(merge.remote_ids - frozenset(output_ids))
        raise LosslessChapterUpdateError(
            "Updated EPUB failed lossless validation "
            f"({missing_historical} historical and {missing_remote} current-source chapters missing)."
        )


def _realign_adapter_chapter_index(
    adapter: Any,
    remote_chapters: Sequence[Mapping[str, Any]],
    merged_chapters: Sequence[Mapping[str, Any]],
) -> None:
    """Keep adapter URL-index caches valid after historical chapters are inserted."""

    chapter_index = getattr(adapter, "chapterURLIndex", None)
    if not isinstance(chapter_index, dict) or not chapter_index:
        return

    opaque_id_by_chapter_id: Dict[str, Any] = {}
    for opaque_id, remote_index in chapter_index.items():
        if not isinstance(remote_index, int) or not 0 <= remote_index < len(remote_chapters):
            raise LosslessChapterUpdateError("FanFicFare adapter returned an invalid chapter URL index.")
        remote_url = str(remote_chapters[remote_index].get("url") or "")
        chapter_id = _canonical_chapter_id(adapter.normalize_chapterurl, remote_url)
        opaque_id_by_chapter_id[chapter_id] = opaque_id

    realigned_index: Dict[Any, int] = {}
    for merged_index, chapter in enumerate(merged_chapters):
        chapter_id = _canonical_chapter_id(adapter.normalize_chapterurl, str(chapter.get("url") or ""))
        opaque_id = opaque_id_by_chapter_id.get(chapter_id)
        if opaque_id is not None:
            realigned_index[opaque_id] = merged_index
    adapter.chapterURLIndex = realigned_index


def _run_fff_lossless_update(
    source_url: str,
    existing_epub_path: Path,
    config_paths: Sequence[Path],
    overwrite: bool,
) -> _LosslessUpdateResult:
    """Update an EPUB through FFF using chapter URL identity instead of counts."""

    from fanficfare import adapters, cli, writers
    from fanficfare.epubutils import get_update_data

    old_update_data = get_update_data(existing_epub_path)
    old_chapter_count = old_update_data[1]
    old_chapter_map = old_update_data[7]
    if old_chapter_count == 0 or not old_chapter_map:
        raise LosslessChapterUpdateError("Existing EPUB has no identifiable FanFicFare chapter URLs.")
    if old_chapter_count != len(old_chapter_map):
        raise LosslessChapterUpdateError(
            f"Existing EPUB has {old_chapter_count} chapter files but only "
            f"{len(old_chapter_map)} identifiable chapter URLs."
        )

    args: List[str] = []
    for config_path in config_paths:
        args.extend(["-c", str(config_path)])
    args.extend(["--non-interactive", "--debug", "-U", str(existing_epub_path)])

    parser = cli.mkParser(False)
    options, _ = parser.parse_args(args)
    cli.expandOptions(options)
    cli.setup(options)
    configuration = cli.get_configuration(
        source_url,
        passed_defaultsini=None,
        passed_personalini=None,
        options=options,
        chaptercount=old_chapter_count,
        output_filename=str(existing_epub_path),
    )

    normalized_url, chapter_begin, chapter_end = adapters.get_url_chapter_range(source_url)
    adapter = adapters.getAdapter(configuration, normalized_url)
    adapter.setChaptersRange(chapter_begin, chapter_end)
    adapter.getStoryMetadataOnly()

    remote_chapters = adapter.get_chapters()
    merge = _build_lossless_chapter_merge(
        existing_urls=list(old_chapter_map),
        existing_data=old_update_data[8],
        remote_chapters=remote_chapters,
        normalize_url=adapter.normalize_chapterurl,
    )
    if not overwrite and not merge.new_ids:
        logger.info(
            "No new chapters for %s; source is missing %s historical chapters that remain preserved.",
            source_url,
            len(merge.historical_ids),
        )
        return _LosslessUpdateResult(
            changed=False,
            preserved_chapter_count=len(merge.historical_ids),
            new_chapter_count=0,
        )

    _realign_adapter_chapter_index(adapter, remote_chapters, merge.chapters)
    adapter.chapterUrls = merge.chapters
    adapter.story.setMetadata("numChapters", len(merge.chapters))
    (
        _,
        _,
        adapter.oldchapters,
        adapter.oldimgs,
        adapter.oldcover,
        adapter.calibrebookmark,
        adapter.logfile,
        adapter.oldchaptersmap,
        adapter.oldchaptersdata,
    ) = old_update_data[:9]

    temp_file = tempfile.NamedTemporaryFile(
        prefix=f".{existing_epub_path.stem}.update-",
        suffix=".epub",
        dir=existing_epub_path.parent,
        delete=False,
    )
    temp_path = Path(temp_file.name)
    temp_file.close()
    temp_path.unlink()

    try:
        configuration.set("overrides", "output_filename", str(temp_path))
        writer = writers.getWriter("epub", configuration, adapter)
        writer.writeStory()
        if not temp_path.is_file():
            raise LosslessChapterUpdateError("FanFicFare completed without producing an updated EPUB.")
        _validate_lossless_epub(temp_path, merge, adapter.normalize_chapterurl)
        temp_path.replace(existing_epub_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    logger.info(
        "Lossless update for %s added %s chapters and preserved %s chapters no longer listed by the source.",
        source_url,
        len(merge.new_ids),
        len(merge.historical_ids),
    )
    return _LosslessUpdateResult(
        changed=True,
        preserved_chapter_count=len(merge.historical_ids),
        new_chapter_count=len(merge.new_ids),
    )


async def _enqueue_audiobook_refresh(book: models.Book, db) -> None:
    """Queue every audio derivative affected by refreshed or cleaned content."""
    await db.refresh(book)
    if book.audiobook_enabled:
        content_version = book.content_version or 1
        book.audiobook_pending_content_version = max(
            book.audiobook_pending_content_version or 0,
            content_version,
        )
        active_statuses = {"ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"}
        if book.audiobook_pipeline_status not in active_statuses:
            transition_state(
                book,
                "audiobook_pipeline_status",
                AUDIOBOOK_PIPELINE,
                AudiobookPipelineStatus.INGESTING,
                context=f"book {book.id}",
            )
        await db.commit()

        from .audiobook_queue import AudiobookQueue, get_audiobook_queue

        legacy_queue = get_audiobook_queue()
        if not isinstance(legacy_queue, AudiobookQueue) and not legacy_queue.has_book_job(book.id):
            await legacy_queue.enqueue(book.id)
    from .processing_queue import queue_audio_reconciliation

    await queue_audio_reconciliation(book, db)


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

    Returns None when overwrite=False and the source has no chapter URLs that are
    new to the existing EPUB. Existing EPUBs are updated from the ordered union of
    saved and current-source chapter URLs, so source-removed chapters are retained.
    """
    LIBRARY_PATH.mkdir(exist_ok=True)
    config_paths = get_fff_config_paths()

    async with _fff_lock:
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
            loop = asyncio.get_running_loop()
            try:
                update_result = await loop.run_in_executor(
                    None,
                    _run_fff_lossless_update,
                    source_url,
                    updated_epub_path,
                    config_paths,
                    overwrite,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"FanFicFare lossless update failed: {exc}",
                ) from exc
            if not update_result.changed:
                return None
        else:
            args: List[str] = []
            for config_path in config_paths:
                args.extend(["-c", str(config_path)])
            args.extend(["--non-interactive", "--debug"])
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
                transition_state(db_book, "download_status", WEB_IMPORT, WebImportStatus.ERROR, context=f"book {book_id}")
                db_book.title = "Error: FFF produced no epub for new URL"
                await db.commit()
                return
            new_epub_path, metadata = result

            existing = await crud.get_book_by_title_and_author(db, title=metadata["title"], author=metadata["author"])
            if existing and existing.id != book_id and existing.source_type == models.SourceType.web:
                new_epub_path.unlink(missing_ok=True)
                transition_state(db_book, "download_status", WEB_IMPORT, WebImportStatus.ERROR, context=f"book {book_id}")
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

            transition_state(db_book, "download_status", WEB_IMPORT, None, context=f"book {book_id}")
            await db.commit()
            await db.refresh(db_book)

        except Exception as e:
            logger.error(f"Background download failed for book {book_id}: {e}\n{traceback.format_exc()}")
            try:
                transition_state(db_book, "download_status", WEB_IMPORT, WebImportStatus.ERROR, context=f"book {book_id}")
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
        await _enqueue_audiobook_refresh(db_book, db)
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
            transition_state(db_book, "refresh_status", WEB_REFRESH, WebRefreshStatus.ERROR, context=f"book {book_id}")
            await db.commit()
            return

        transition_state(
            db_book,
            "refresh_status",
            WEB_REFRESH,
            WebRefreshStatus.PROCESSING,
            context=f"book {book_id}",
        )
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
                transition_state(updated_book, "download_status", WEB_IMPORT, None, context=f"book {book_id}")
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
                await _enqueue_audiobook_refresh(updated_book, db)
                await queue_metadata_sync_job(db, trigger="book_update", book_ids=[updated_book.id])

                transition_state(updated_book, "refresh_status", WEB_REFRESH, None, context=f"book {book_id}")
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
            await _enqueue_audiobook_refresh(updated_book, db)
            await queue_metadata_sync_job(db, trigger="book_update", book_ids=[updated_book.id])

            transition_state(updated_book, "refresh_status", WEB_REFRESH, None, context=f"book {book_id}")
            await db.commit()
        except Exception as exc:
            logger.error(
                "Manual refresh failed for book %s: %s\n%s",
                book_id,
                exc,
                traceback.format_exc(),
            )
            try:
                transition_state(db_book, "refresh_status", WEB_REFRESH, WebRefreshStatus.ERROR, context=f"book {book_id}")
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
                else:
                    logger.info(f"No new chapters for {book.title}.")
                    log_entry = schemas.BookLogCreate(
                        book_id=book.id,
                        entry_type="checked",
                        previous_chapter_count=old_chapter_count,
                        new_chapter_count=new_chapter_count,
                        words_added=0,
                    )
                book.master_word_count = new_word_count
                book.current_word_count = new_word_count
                await crud.touch_book_content(db, book)
                await db.commit()
                await crud.create_book_log(db, log_entry)
                await epub_editor.apply_book_cleaning(book, db)
                await _enqueue_audiobook_refresh(book, db)
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
