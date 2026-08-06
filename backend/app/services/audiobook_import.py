"""Import Libation and other human-narrated audiobook files."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..models import (
    AudiobookChapter,
    AudiobookSentence,
    Book,
    ImportedAudiobook,
    ImportedAudiobookCue,
    ImportedAudiobookTrack,
)
from .audiobook_ingestion import ingest_epub

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".m4b", ".mp3", ".mp4", ".ogg", ".opus", ".wav"}
IMPORT_EXTENSIONS = AUDIO_EXTENSIONS | {".cue", ".zip"}
MAX_AUDIOBOOK_UPLOAD_BYTES = 8 * 1024 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
_ASIN_RE = re.compile(r"\[(B[0-9A-Z]{9})\]", re.IGNORECASE)
_CUE_TRACK_RE = re.compile(r"^\s*TRACK\s+(\d+)\s+AUDIO\s*$", re.IGNORECASE)
_CUE_TITLE_RE = re.compile(r'^\s*TITLE\s+"(.*)"\s*$', re.IGNORECASE)
_CUE_INDEX_RE = re.compile(r"^\s*INDEX\s+01\s+(\d+):(\d+):(\d+)\s*$", re.IGNORECASE)
_CHAPTER_NUMBER_RE = re.compile(r"(?:^|\b)chapter\s+(\d+)\b|^\s*(\d+)\s*$", re.IGNORECASE)
_CREDITS_RE = re.compile(r"\b(?:opening|end)\s+credits?\b", re.IGNORECASE)


@dataclass(frozen=True)
class TrackSpec:
    sequence_order: int
    title: str
    audio_path: Path
    start_ms: int
    end_ms: int
    media_type: str

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def imported_audiobook_dir(book_id: int, edition_id: int) -> Path:
    return LIBRARY_PATH / "audiobooks" / str(book_id) / "imports" / str(edition_id)


def relative_library_path(path: Path) -> str:
    return str(path.resolve().relative_to(LIBRARY_PATH.parent.resolve()))


def safe_import_filename(raw_name: str, fallback: str = "audiobook") -> str:
    name = PurePosixPath((raw_name or "").replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f/:]+", "_", name).strip(" .")
    return name or fallback


def asin_from_names(names: list[str]) -> str | None:
    for name in names:
        match = _ASIN_RE.search(name)
        if match:
            return match.group(1).upper()
    return None


def display_name_from_filename(filename: str) -> str:
    value = Path(filename).stem
    value = _ASIN_RE.sub("", value).strip()
    return value or "Imported audiobook"


async def stream_upload_to_path(upload, destination: Path, remaining_bytes: int) -> int:
    """Stream an UploadFile to disk without retaining a multi-GB book in memory."""
    written = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(UPLOAD_CHUNK_BYTES)
            if not chunk:
                return written
            written += len(chunk)
            if written > remaining_bytes:
                raise ValueError("Audiobook upload exceeds the 8 GB per-import limit.")
            handle.write(chunk)


def _safe_zip_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    entries = [entry for entry in archive.infolist() if not entry.is_dir()]
    if len(entries) > 10_000:
        raise ValueError("Audiobook ZIP contains too many files.")
    if sum(entry.file_size for entry in entries) > MAX_AUDIOBOOK_UPLOAD_BYTES:
        raise ValueError("Audiobook ZIP expands beyond the 8 GB import limit.")
    for entry in entries:
        path = PurePosixPath(entry.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Audiobook ZIP contains an unsafe path: {entry.filename}")
    return entries


def _unique_destination(directory: Path, raw_name: str) -> Path:
    safe_name = safe_import_filename(raw_name)
    candidate = directory / safe_name
    stem, suffix = candidate.stem, candidate.suffix
    number = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{number}{suffix}"
        number += 1
    return candidate


def _copy_zip_entry(archive: zipfile.ZipFile, entry: zipfile.ZipInfo, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(entry) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target, length=UPLOAD_CHUNK_BYTES)


def _extract_archive_sources(archive_path: Path, source_dir: Path) -> tuple[list[Path], list[Path]]:
    with zipfile.ZipFile(archive_path) as archive:
        entries = _safe_zip_entries(archive)
        audio_entries = [entry for entry in entries if Path(entry.filename).suffix.lower() in AUDIO_EXTENSIONS]
        cue_entries = [entry for entry in entries if Path(entry.filename).suffix.lower() == ".cue"]
        if not audio_entries:
            raise ValueError(f"{archive_path.name} contains no supported audio files.")

        selected_audio = _preferred_audio_files(audio_entries, lambda entry: Path(entry.filename))
        audio_paths: list[Path] = []
        cue_paths: list[Path] = []
        for entry in selected_audio:
            destination = _unique_destination(source_dir, entry.filename)
            _copy_zip_entry(archive, entry, destination)
            audio_paths.append(destination)
        for entry in cue_entries:
            destination = _unique_destination(source_dir, entry.filename)
            _copy_zip_entry(archive, entry, destination)
            cue_paths.append(destination)
        return audio_paths, cue_paths


def _preferred_audio_files(items: list, path_for_item=lambda item: item) -> list:
    """Discard Libation's duplicate MP3 rendition when an M4B is present."""
    m4b_items = [item for item in items if path_for_item(item).suffix.lower() == ".m4b"]
    return m4b_items or items


def _prepare_sources(edition_dir: Path) -> tuple[list[Path], list[Path]]:
    incoming_dir = edition_dir / "incoming"
    source_dir = edition_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    # A failed import may already have moved a direct upload or extracted a
    # large Libation archive. Reuse those durable source files on retry instead
    # of requiring another upload (or duplicating a multi-gigabyte recording).
    existing_sources = sorted(path for path in source_dir.iterdir() if path.is_file())
    audio_paths = [path for path in existing_sources if path.suffix.lower() in AUDIO_EXTENSIONS]
    cue_paths = [path for path in existing_sources if path.suffix.lower() == ".cue"]
    for incoming in sorted(path for path in incoming_dir.iterdir() if path.is_file()):
        suffix = incoming.suffix.lower()
        if suffix == ".zip":
            if audio_paths:
                continue
            archive_audio, archive_cues = _extract_archive_sources(incoming, source_dir)
            audio_paths.extend(archive_audio)
            cue_paths.extend(archive_cues)
        elif suffix in AUDIO_EXTENSIONS:
            destination = _unique_destination(source_dir, incoming.name)
            incoming.replace(destination)
            audio_paths.append(destination)
        elif suffix == ".cue":
            destination = _unique_destination(source_dir, incoming.name)
            incoming.replace(destination)
            cue_paths.append(destination)
    audio_paths = _preferred_audio_files(audio_paths)
    if not audio_paths:
        raise ValueError("No supported audiobook audio was uploaded.")
    return audio_paths, cue_paths


async def _probe_audio(path: Path) -> tuple[int, list[dict]]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required to import audiobooks.")
    process = await asyncio.create_subprocess_exec(
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_chapters",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        message = stderr.decode("utf-8", errors="replace")[:500]
        raise ValueError(f"Could not inspect {path.name}: {message}")
    payload = json.loads(stdout)
    duration_ms = round(float(payload.get("format", {}).get("duration") or 0) * 1000)
    if duration_ms <= 0:
        raise ValueError(f"Could not determine the duration of {path.name}.")
    return duration_ms, payload.get("chapters") or []


def _read_cue_text(path: Path) -> str:
    payload = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def _parse_cue(path: Path, audio_path: Path, duration_ms: int, media_type: str) -> list[TrackSpec]:
    tracks: list[tuple[int, str, int]] = []
    current_number: int | None = None
    current_title: str | None = None
    for line in _read_cue_text(path).splitlines():
        if match := _CUE_TRACK_RE.match(line):
            current_number = int(match.group(1))
            current_title = None
        elif current_number is not None and (match := _CUE_TITLE_RE.match(line)):
            current_title = match.group(1).strip()
        elif current_number is not None and (match := _CUE_INDEX_RE.match(line)):
            minutes, seconds, frames = (int(value) for value in match.groups())
            start_ms = round((minutes * 60 + seconds + frames / 75) * 1000)
            tracks.append((current_number, current_title or f"Track {current_number}", start_ms))
            current_number = None
    specs: list[TrackSpec] = []
    for index, (number, title, start_ms) in enumerate(tracks):
        end_ms = tracks[index + 1][2] if index + 1 < len(tracks) else duration_ms
        if end_ms > start_ms:
            specs.append(
                TrackSpec(
                    sequence_order=number,
                    title=title,
                    audio_path=audio_path,
                    start_ms=start_ms,
                    end_ms=min(end_ms, duration_ms),
                    media_type=media_type,
                )
            )
    return specs


def _media_type(path: Path) -> str:
    return {
        ".m4a": "audio/mp4",
        ".m4b": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".opus": "audio/ogg",
    }.get(path.suffix.lower(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")


async def _track_specs(audio_paths: list[Path], cue_paths: list[Path]) -> tuple[list[TrackSpec], int]:
    probes: dict[Path, tuple[int, list[dict]]] = {}
    for path in audio_paths:
        probes[path] = await _probe_audio(path)
    total_duration_ms = sum(duration for duration, _chapters in probes.values())

    if len(audio_paths) == 1 and cue_paths:
        audio_path = audio_paths[0]
        specs = _parse_cue(
            cue_paths[0],
            audio_path,
            probes[audio_path][0],
            _media_type(audio_path),
        )
        if specs:
            return specs, total_duration_ms

    if len(audio_paths) == 1 and probes[audio_paths[0]][1]:
        audio_path = audio_paths[0]
        embedded: list[TrackSpec] = []
        for index, chapter in enumerate(probes[audio_path][1], start=1):
            start_ms = round(float(chapter.get("start_time") or 0) * 1000)
            end_ms = round(float(chapter.get("end_time") or 0) * 1000)
            tags = chapter.get("tags") or {}
            if end_ms > start_ms:
                embedded.append(
                    TrackSpec(
                        sequence_order=index,
                        title=str(tags.get("title") or f"Track {index}"),
                        audio_path=audio_path,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        media_type=_media_type(audio_path),
                    )
                )
        if embedded:
            return embedded, total_duration_ms

    specs = []
    for index, audio_path in enumerate(audio_paths, start=1):
        duration_ms = probes[audio_path][0]
        specs.append(
            TrackSpec(
                sequence_order=index,
                title=display_name_from_filename(audio_path.name),
                audio_path=audio_path,
                start_ms=0,
                end_ms=duration_ms,
                media_type=_media_type(audio_path),
            )
        )
    return specs, total_duration_ms


def _chapter_identity(title: str | None) -> tuple[str, int | str] | None:
    value = " ".join((title or "").split()).strip()
    if not value or _CREDITS_RE.search(value):
        return None
    if match := _CHAPTER_NUMBER_RE.search(value):
        return "chapter", int(match.group(1) or match.group(2))
    lowered = value.casefold()
    if "epilogue" in lowered:
        return "named", "epilogue"
    if "prologue" in lowered:
        return "named", "prologue"
    return "named", re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def _chapter_match(spec: TrackSpec, chapters: list[AudiobookChapter]) -> AudiobookChapter | None:
    wanted = _chapter_identity(spec.title)
    if wanted is None:
        return None
    candidates = [chapter for chapter in chapters if _chapter_identity(chapter.title) == wanted]
    return candidates[0] if candidates else None


def _sentence_weight(text: str) -> int:
    # A small fixed pause allowance prevents very short sentences from becoming
    # unclickably narrow while still tracking normal spoken-text length.
    return max(1, len(re.sub(r"\s+", "", text))) + 10


async def rebuild_estimated_cues(track: ImportedAudiobookTrack, db: AsyncSession) -> int:
    await db.execute(delete(ImportedAudiobookCue).where(ImportedAudiobookCue.track_id == track.id))
    if track.matched_chapter_id is None:
        await db.commit()
        return 0
    result = await db.execute(
        select(AudiobookSentence)
        .where(AudiobookSentence.chapter_id == track.matched_chapter_id)
        .order_by(AudiobookSentence.sequence_order)
    )
    sentences = list(result.scalars().all())
    if not sentences:
        await db.commit()
        return 0
    weights = [_sentence_weight(sentence.original_text) for sentence in sentences]
    total_weight = sum(weights)
    cumulative_weight = 0
    prior_boundary = track.source_start_ms
    for index, (sentence, weight) in enumerate(zip(sentences, weights, strict=True)):
        cumulative_weight += weight
        boundary = (
            track.source_end_ms
            if index == len(sentences) - 1
            else track.source_start_ms + round(track.duration_ms * cumulative_weight / total_weight)
        )
        db.add(
            ImportedAudiobookCue(
                track_id=track.id,
                sentence_id=sentence.id,
                sequence_order=index,
                clip_begin_ms=prior_boundary,
                clip_end_ms=max(prior_boundary + 1, boundary),
                confidence=0.25,
                method="estimated",
            )
        )
        prior_boundary = boundary
    await db.commit()
    return len(sentences)


async def ensure_span_anchored_text(book: Book, db: AsyncSession) -> list[AudiobookChapter]:
    chapters = await crud.audiobook.get_chapters_for_book(db, book.id)
    content_version = book.content_version or 1
    chapters_are_current = (
        chapters
        and book.audiobook_source_content_version == content_version
        and book.audiobook_text_content_version == content_version
    )
    if chapters_are_current:
        return chapters
    prior_status = book.audiobook_pipeline_status
    await ingest_epub(book.id, db)
    await db.refresh(book)
    # Importing narration must not silently opt the user into an unattended AI
    # generation run. The generated pipeline remains exactly where it was.
    book.audiobook_pipeline_status = prior_status
    await db.commit()
    return await crud.audiobook.get_chapters_for_book(db, book.id)


async def process_import(edition_id: int, db: AsyncSession) -> None:
    edition = await db.get(ImportedAudiobook, edition_id)
    if edition is None:
        return
    edition.status = "importing"
    edition.error = None
    edition.progress_detail = "Inspecting uploaded files"
    await db.commit()
    try:
        book = await db.get(Book, edition.book_id)
        if book is None:
            raise ValueError("The selected library book no longer exists.")
        edition_dir = imported_audiobook_dir(book.id, edition.id)
        audio_paths, cue_paths = _prepare_sources(edition_dir)
        specs, duration_ms = await _track_specs(audio_paths, cue_paths)
        edition.duration_ms = duration_ms
        edition.source_type = "libation" if cue_paths or edition.asin else "upload"
        edition.progress_total = len(specs)
        edition.progress_current = 0
        edition.progress_detail = "Preparing synchronized book text"
        await db.commit()

        chapters = await ensure_span_anchored_text(book, db)
        await db.execute(delete(ImportedAudiobookTrack).where(ImportedAudiobookTrack.imported_audiobook_id == edition.id))
        await db.commit()
        for index, spec in enumerate(specs, start=1):
            matched = _chapter_match(spec, chapters)
            track = ImportedAudiobookTrack(
                imported_audiobook_id=edition.id,
                matched_chapter_id=matched.id if matched else None,
                sequence_order=spec.sequence_order,
                title=spec.title,
                audio_file_path=relative_library_path(spec.audio_path),
                media_type=spec.media_type,
                source_start_ms=spec.start_ms,
                source_end_ms=spec.end_ms,
                duration_ms=spec.duration_ms,
            )
            db.add(track)
            await db.flush()
            await rebuild_estimated_cues(track, db)
            edition.progress_current = index
            edition.progress_detail = f"Matched track {index} of {len(specs)}"
            await db.commit()

        matched_count = sum(1 for spec in specs if _chapter_match(spec, chapters))
        edition.status = "ready"
        edition.alignment_method = "estimated"
        edition.matched_content_version = book.content_version or 1
        edition.progress_current = len(specs)
        edition.progress_total = len(specs)
        edition.progress_detail = f"Ready: {matched_count} of {len(specs)} tracks matched"
        edition.error = None
        await db.commit()
        shutil.rmtree(edition_dir / "incoming", ignore_errors=True)
    except Exception as exc:
        logger.exception("Audiobook import %s failed.", edition_id)
        await db.rollback()
        edition = await db.get(ImportedAudiobook, edition_id)
        if edition is not None:
            edition.status = "error"
            edition.error = str(exc)
            edition.progress_detail = "Import failed"
            await db.commit()


async def rematch_imported_audiobook(edition_id: int, db: AsyncSession) -> int:
    """Rematch existing human-audio tracks after the book text changes."""
    edition = await db.get(ImportedAudiobook, edition_id)
    if edition is None:
        raise ValueError("Imported audiobook no longer exists.")
    book = await db.get(Book, edition.book_id)
    if book is None:
        raise ValueError("The selected library book no longer exists.")

    edition.status = "importing"
    edition.alignment_error = None
    edition.progress_current = 0
    edition.progress_detail = "Preparing current cleaned book text"
    await db.commit()
    chapters = await ensure_span_anchored_text(book, db)
    result = await db.execute(
        select(ImportedAudiobookTrack)
        .where(ImportedAudiobookTrack.imported_audiobook_id == edition.id)
        .order_by(ImportedAudiobookTrack.sequence_order)
    )
    tracks = list(result.scalars().all())
    edition.progress_total = len(tracks)
    await db.commit()

    matched_count = 0
    for index, track in enumerate(tracks, start=1):
        spec = TrackSpec(
            sequence_order=track.sequence_order,
            title=track.title,
            audio_path=(LIBRARY_PATH.parent / track.audio_file_path).resolve(),
            start_ms=track.source_start_ms,
            end_ms=track.source_end_ms,
            media_type=track.media_type,
        )
        matched = _chapter_match(spec, chapters)
        track.matched_chapter_id = matched.id if matched else None
        track.alignment_score = None
        await db.commit()
        await rebuild_estimated_cues(track, db)
        matched_count += int(matched is not None)
        edition.progress_current = index
        edition.progress_detail = f"Rematched track {index} of {len(tracks)}"
        await db.commit()

    edition.status = "ready"
    edition.alignment_method = "estimated"
    edition.matched_content_version = book.content_version or 1
    edition.progress_detail = f"Ready: {matched_count} of {len(tracks)} tracks matched"
    edition.error = None
    await db.commit()
    return matched_count


async def rematch_track(
    track: ImportedAudiobookTrack,
    chapter_id: int | None,
    db: AsyncSession,
) -> int:
    if chapter_id is not None:
        chapter = await db.get(AudiobookChapter, chapter_id)
        edition = await db.get(ImportedAudiobook, track.imported_audiobook_id)
        if chapter is None or edition is None or chapter.book_id != edition.book_id:
            raise ValueError("Chapter does not belong to this audiobook's book.")
    track.matched_chapter_id = chapter_id
    track.alignment_score = None
    edition = await db.get(ImportedAudiobook, track.imported_audiobook_id)
    if edition is not None:
        edition.alignment_method = "estimated"
        edition.alignment_error = None
    await db.commit()
    await db.refresh(track)
    return await rebuild_estimated_cues(track, db)
