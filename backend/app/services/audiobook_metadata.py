"""Read audiobook identity from source tags, CUE headers, and Libation names."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path, PurePosixPath
from typing import Any, TypedDict, cast
from decimal import Decimal
import re

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Book, ImportedAudiobook, SourceType

logger = logging.getLogger(__name__)
_ASIN = re.compile(r"\[((?:B[0-9A-Z]{9})|(?:[0-9]{9}[0-9X]))\]", re.I)
_SERIES = re.compile(r"^(.+?)[_:]\s*(.+?),\s*(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?)$", re.I)
_EXTENSIONS = {".m4b", ".m4a", ".mp3", ".mp4", ".aac", ".flac", ".ogg", ".opus", ".wav", ".cue", ".zip"}


class AudioMetadata(TypedDict, total=False):
    title: str | None
    author: str | None
    series: str | None
    series_index: float
    asin: str
    narrator: str | None
    description: str | None
    genre: str | None


def filename_metadata(names: list[str]) -> AudioMetadata:
    parts = [part for name in names for part in PurePosixPath(name.replace("\\", "/")).parts]
    value = next((part for part in parts if _ASIN.search(part)), parts[0] if len(parts) == 1 else "")
    if not value and names:
        value = PurePosixPath(names[0].replace("\\", "/")).name
    if Path(value).suffix.lower() in _EXTENSIONS:
        value = value[: -len(Path(value).suffix)]
    asin = _ASIN.search(value)
    value = _ASIN.sub("", value).strip(" ._-")
    result: AudioMetadata = {"title": value or "Imported audiobook"}
    if asin:
        result["asin"] = asin.group(1).upper()
    series = _SERIES.fullmatch(value)
    if series and float(series.group(3)) < 10000:
        result.update(
            {"title": series.group(1).strip(), "series": series.group(2).strip(), "series_index": float(series.group(3))}
        )
    return result


def cue_metadata(path: Path) -> AudioMetadata:
    # Album-level fields only: TRACK titles and performers describe individual tracks.
    payload = path.read_bytes()[:256_000]
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = payload.decode("cp1252", errors="replace")
    result: AudioMetadata = {}
    for line in content.splitlines():
        if re.match(r"\s*TRACK\s+\d+", line, re.I):
            break
        match = re.fullmatch(r'\s*(TITLE|PERFORMER)\s+"([^"]+)"\s*', line, re.I)
        if match:
            if match.group(1).upper() == "TITLE":
                result["title"] = match.group(2).strip()
            else:
                result["author"] = match.group(2).strip()
    return result


def tag_metadata(payload: dict[str, Any], *, single_file: bool) -> AudioMetadata:
    tags = {str(key).casefold(): str(value).strip() for key, value in payload.get("format", {}).get("tags", {}).items()}

    def value(*keys: str) -> str | None:
        return next((tags[key][:2000] for key in keys if tags.get(key)), None)

    # In a multi-file book, a file TITLE usually names a chapter. ALBUM names the book.
    result: AudioMetadata = {
        "title": value("album") or (value("title") if single_file else None),
        "author": value("author", "artist", "album_artist", "albumartist"),
        "series": value("series", "series_name", "series-name", "mvnm"),
        "narrator": value("narrator", "narrated_by"),
        "description": value("description", "synopsis", "comment"),
        "genre": value("genre"),
    }
    number = value("series_index", "series-part", "series_part", "series_position", "mvin")
    if number and re.fullmatch(r"\d{1,4}(?:\.\d{1,2})?", number):
        result["series_index"] = float(number)
    asin = value("asin", "audible_asin", "audibleasin")
    if asin and re.fullmatch(r"(?:B[0-9A-Z]{9}|[0-9]{9}[0-9X])", asin, re.I):
        result["asin"] = asin.upper()
    return cast(AudioMetadata, {key: val for key, val in result.items() if val is not None})


async def _run(*command: str) -> bytes:
    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except (TimeoutError, asyncio.CancelledError):
        process.kill()
        await process.communicate()
        raise
    if process.returncode:
        raise ValueError(stderr.decode("utf-8", errors="replace")[:500])
    return stdout


async def enrich_audio_only_book(
    book: Book, edition: ImportedAudiobook, audio_paths: list[Path], cue_paths: list[Path], db: AsyncSession
) -> None:
    if book.source_type != SourceType.audiobook:
        return
    metadata = filename_metadata(edition.original_filenames or [audio_paths[0].name])
    sources = ["filename"]
    for path in cue_paths[:1]:
        try:
            cue = cue_metadata(path)
            metadata.update(cue)
            if cue:
                sources.append("cue")
        except OSError:
            logger.warning("Could not read audiobook CUE metadata for edition %s", edition.id, exc_info=True)
    cover_path = None
    try:
        payload = json.loads(
            await _run("ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(audio_paths[0]))
        )
        tags = tag_metadata(payload, single_file=len(audio_paths) == 1)
        metadata.update(tags)
        if tags:
            sources.append("audio_tags")
        cover_stream = next(
            (stream for stream in payload.get("streams", []) if stream.get("disposition", {}).get("attached_pic")), None
        )
        if not book.cover_path and cover_stream:
            destination = audio_paths[0].parent.parent / "cover.jpg"
            try:
                await _run(
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(audio_paths[0]),
                    "-map",
                    f"0:{cover_stream['index']}",
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=1200:1200:force_original_aspect_ratio=decrease",
                    "-y",
                    str(destination),
                )
                cover_path = destination
            except (OSError, ValueError, TimeoutError):
                destination.unlink(missing_ok=True)
                logger.warning("Could not extract audiobook cover for edition %s", edition.id, exc_info=True)
    except (OSError, ValueError, TimeoutError):
        logger.warning(
            "Could not read audiobook tags for edition %s; keeping filename/CUE metadata", edition.id, exc_info=True
        )

    # Reload after probing so edits made while an import is running take precedence.
    await db.refresh(book)
    details = dict(book.metadata_details or {})
    previous = dict(details.get("audiobook_import") or {})
    if previous.get("inferred_title") == book.title and metadata.get("title"):
        book.title = metadata["title"]
        previous["inferred_title"] = book.title
    if not book.author or book.author == "Unknown author":
        book.author = metadata.get("author") or book.author
    if not book.series and metadata.get("series"):
        book.series = metadata["series"]
        series_index = metadata.get("series_index")
        book.series_index = Decimal(str(series_index)) if series_index is not None else None
    if not book.cover_path and cover_path:
        # The edition path always sits under library/audiobooks/<book>/imported/<edition>.
        from .audiobook_import import relative_library_path

        book.cover_path = relative_library_path(cover_path)
    identifiers = dict(book.metadata_remote_ids or {})
    if metadata.get("asin") or edition.asin:
        identifiers.setdefault("asin", metadata.get("asin") or edition.asin)
        edition.asin = edition.asin or metadata.get("asin")
    book.metadata_remote_ids = identifiers or None
    details["audiobook_import"] = {**previous, "sources": sources, "metadata": metadata}
    book.metadata_details = details
    await db.commit()


async def queue_audio_metadata_lookup(book: Book, db: AsyncSession) -> None:
    """Use the normal confidence/review workflow; lookup failure must not fail playback."""
    if book.source_type != SourceType.audiobook:
        return
    details = dict(book.metadata_details or {})
    imported = dict(details.get("audiobook_import") or {})
    if imported.get("lookup_queued"):
        return
    from .metadata_jobs import queue_metadata_sync_job

    try:
        await queue_metadata_sync_job(db, trigger="new_book", book_ids=[book.id])
        imported["lookup_queued"] = True
        book.metadata_details = {**details, "audiobook_import": imported}
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning("Could not queue metadata lookup after audiobook import", exc_info=True)
