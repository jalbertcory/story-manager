"""Import Libation and other human-narrated audiobook files."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
from typing import Awaitable, Callable
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..lifecycle import (
    ALIGNMENT_METHOD,
    AUDIOBOOK_PIPELINE,
    IMPORTED_AUDIOBOOK,
    AlignmentMethod,
    ImportedAudiobookStatus,
    transition_state,
)
from ..models import (
    AudiobookChapter,
    AudiobookSentence,
    Book,
    ImportedAudiobook,
    ImportedAudiobookCue,
    ImportedAudiobookTrack,
)
from .audiobook_ingestion import ingest_epub
from .audiobook_metadata import enrich_audio_only_book, queue_audio_metadata_lookup

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".m4b", ".mp3", ".mp4", ".ogg", ".opus", ".wav"}
IMPORT_EXTENSIONS = AUDIO_EXTENSIONS | {".cue", ".zip"}
CURRENT_DERIVED_FORMAT_VERSION = 1
# Increment when an imported human audiobook must be rebuilt to benefit from
# changes to text ingestion, chapter matching, cue generation, or alignment.
CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION = 1
SOURCE_MANIFEST_FORMAT = "story-manager-audiobook-source"
SOURCE_MANIFEST_VERSION = 1
MAX_AUDIOBOOK_UPLOAD_BYTES = 8 * 1024 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
_ASIN_RE = re.compile(r"\[((?:B[0-9A-Z]{9})|(?:[0-9]{9}[0-9X]))\]", re.IGNORECASE)
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
    source_audio_path: Path | None = None
    source_start_ms: int | None = None
    source_end_ms: int | None = None

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def immutable_audio_path(self) -> Path:
        return self.source_audio_path or self.audio_path

    @property
    def immutable_start_ms(self) -> int:
        return self.start_ms if self.source_start_ms is None else self.source_start_ms

    @property
    def immutable_end_ms(self) -> int:
        return self.end_ms if self.source_end_ms is None else self.source_end_ms


@dataclass(frozen=True)
class HumanAudiobookRebuildResult:
    matched_track_count: int
    track_count: int
    realign: bool
    derived_revision: int


def _chapter_file_suffix(source: Path) -> str:
    """Return an audio-only extension that ffmpeg and browsers both understand."""
    if source.suffix.lower() in {".m4b", ".mp4"}:
        return ".m4a"
    return source.suffix.lower()


async def _extract_chapter_audio(spec: TrackSpec, destination: Path) -> None:
    """Copy one chapter range into its own seekable audio file."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to split chaptered audiobooks.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.stem}.part{destination.suffix}")
    temporary.unlink(missing_ok=True)
    command = [
        ffmpeg,
        "-v",
        "error",
        "-ss",
        f"{spec.start_ms / 1000:.3f}",
        "-i",
        str(spec.audio_path),
        "-t",
        f"{spec.duration_ms / 1000:.3f}",
        "-map",
        "0:a:0",
        "-vn",
        "-c:a",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-map_metadata",
        "-1",
    ]
    if destination.suffix == ".m4a":
        command.extend(["-movflags", "+faststart"])
    command.extend(["-y", str(temporary)])
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await process.communicate()
    if process.returncode:
        temporary.unlink(missing_ok=True)
        message = stderr.decode("utf-8", errors="replace")[:500]
        raise ValueError(f"Could not split {spec.title!r} into a chapter file: {message}")
    temporary.replace(destination)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(UPLOAD_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: dict) -> bytes:
    content = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    return content


async def build_source_manifest(edition: ImportedAudiobook, edition_dir: Path) -> tuple[Path, str, int]:
    """Inventory the immutable files from which every derived revision is built."""
    source_dir = edition_dir / "source"
    source_files = sorted(path for path in source_dir.iterdir() if path.is_file() and path.name != "manifest.json")
    if not source_files:
        raise ValueError("Imported audiobook source files are missing.")
    entries = []
    total_size = 0
    for source in source_files:
        size = source.stat().st_size
        total_size += size
        entries.append(
            {
                "name": source.name,
                "role": "cue" if source.suffix.lower() == ".cue" else "audio",
                "size_bytes": size,
                "sha256": await asyncio.to_thread(_sha256_file, source),
            }
        )
    payload = {
        "format": SOURCE_MANIFEST_FORMAT,
        "format_version": SOURCE_MANIFEST_VERSION,
        "asin": edition.asin,
        "original_filenames": edition.original_filenames or [],
        "files": entries,
    }
    manifest_path = source_dir / "manifest.json"
    content = _atomic_write_json(manifest_path, payload)
    return manifest_path, hashlib.sha256(content).hexdigest(), total_size


def _next_derived_revision(edition: ImportedAudiobook, edition_dir: Path) -> int:
    revisions = [edition.derived_revision or 0]
    derived_dir = edition_dir / "derived"
    if derived_dir.is_dir():
        for candidate in derived_dir.glob("revision-*"):
            try:
                revisions.append(int(candidate.name.removeprefix("revision-")))
            except ValueError:
                continue
    return max(revisions) + 1


async def _materialize_chapter_audio(
    specs: list[TrackSpec],
    edition_dir: Path,
    revision: int,
    progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> list[TrackSpec]:
    """Build a verified, immutable derived revision before it becomes active."""
    source_counts: dict[Path, int] = {}
    for spec in specs:
        source_counts[spec.audio_path] = source_counts.get(spec.audio_path, 0) + 1
    derived_dir = edition_dir / "derived"
    final_dir = derived_dir / f"revision-{revision}"
    staging_dir = derived_dir / f".revision-{revision}-{uuid4().hex}.staging"
    staging_dir.mkdir(parents=True, exist_ok=False)
    materialized: list[TrackSpec] = []
    try:
        for index, spec in enumerate(specs, start=1):
            if source_counts[spec.audio_path] == 1:
                materialized.append(spec)
            else:
                suffix = _chapter_file_suffix(spec.audio_path)
                destination = staging_dir / f"track-{index:04d}{suffix}"
                await _extract_chapter_audio(spec, destination)
                await _probe_audio(destination)
                materialized.append(
                    TrackSpec(
                        sequence_order=spec.sequence_order,
                        title=spec.title,
                        audio_path=destination,
                        start_ms=0,
                        end_ms=spec.duration_ms,
                        media_type=_media_type(destination),
                        source_audio_path=spec.immutable_audio_path,
                        source_start_ms=spec.immutable_start_ms,
                        source_end_ms=spec.immutable_end_ms,
                    )
                )
            if progress is not None:
                await progress(index, len(specs))
        _atomic_write_json(
            staging_dir / "manifest.json",
            {
                "format": "story-manager-audiobook-derived",
                "format_version": CURRENT_DERIVED_FORMAT_VERSION,
                "revision": revision,
                "tracks": [
                    {
                        "sequence_order": spec.sequence_order,
                        "file": spec.audio_path.name if spec.audio_path.is_relative_to(staging_dir) else None,
                        "duration_ms": spec.duration_ms,
                    }
                    for spec in materialized
                ],
            },
        )
        staging_dir.replace(final_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    return [
        TrackSpec(
            sequence_order=spec.sequence_order,
            title=spec.title,
            audio_path=(final_dir / spec.audio_path.name if spec.audio_path.is_relative_to(staging_dir) else spec.audio_path),
            start_ms=spec.start_ms,
            end_ms=spec.end_ms,
            media_type=spec.media_type,
            source_audio_path=spec.source_audio_path,
            source_start_ms=spec.source_start_ms,
            source_end_ms=spec.source_end_ms,
        )
        for spec in materialized
    ]


def cleanup_old_derived_revisions(edition_dir: Path, active_revision: int) -> None:
    """Remove rebuildable revisions only after the database cutover succeeds."""
    derived_dir = edition_dir / "derived"
    if derived_dir.is_dir():
        for candidate in derived_dir.iterdir():
            if candidate.name != f"revision-{active_revision}":
                shutil.rmtree(candidate, ignore_errors=True)
    # ``tracks`` was used briefly by the pre-revision chapter-splitting implementation.
    shutil.rmtree(edition_dir / "tracks", ignore_errors=True)


async def upgrade_imported_audiobook(edition_id: int, db: AsyncSession) -> int:
    """Rebuild chapter assets from immutable source files without re-uploading."""
    edition = await db.get(ImportedAudiobook, edition_id)
    if edition is None:
        raise ValueError("Imported audiobook no longer exists.")
    result = await db.execute(
        select(ImportedAudiobookTrack)
        .where(ImportedAudiobookTrack.imported_audiobook_id == edition.id)
        .order_by(ImportedAudiobookTrack.sequence_order)
    )
    tracks = list(result.scalars().all())
    if not tracks:
        raise ValueError("Imported audiobook has no tracks to upgrade.")

    edition_dir = imported_audiobook_dir(edition.book_id, edition.id)
    edition.progress_current = 0
    edition.progress_total = len(tracks)
    edition.progress_detail = "Verifying immutable audiobook sources"
    await db.commit()
    manifest_path, manifest_sha, source_size = await build_source_manifest(edition, edition_dir)
    edition.source_manifest_file_path = relative_library_path(manifest_path)
    edition.source_manifest_sha256 = manifest_sha
    edition.source_size_bytes = source_size
    revision = _next_derived_revision(edition, edition_dir)
    source_root = (edition_dir / "source").resolve()

    specs = []
    for track in tracks:
        source_path = track.source_audio_file_path or track.audio_file_path
        source = (LIBRARY_PATH.parent / source_path).resolve()
        if not source.is_relative_to(source_root):
            raise ValueError(f"Immutable audio source for {track.title!r} is outside the edition source directory.")
        if not source.is_file():
            raise ValueError(f"Immutable audio source for {track.title!r} is missing.")
        begin = track.source_clip_begin_ms if track.source_clip_begin_ms is not None else track.source_start_ms
        end = track.source_clip_end_ms if track.source_clip_end_ms is not None else track.source_end_ms
        specs.append(
            TrackSpec(
                sequence_order=track.sequence_order,
                title=track.title,
                audio_path=source,
                start_ms=begin,
                end_ms=end,
                media_type=_media_type(source),
            )
        )

    async def update_progress(current: int, total: int) -> None:
        edition.progress_current = current
        edition.progress_total = total
        edition.progress_detail = f"Building chapter audio {current} of {total}"
        await db.commit()

    materialized = await _materialize_chapter_audio(specs, edition_dir, revision, update_progress)
    cue_result = await db.execute(
        select(ImportedAudiobookCue).where(ImportedAudiobookCue.track_id.in_([track.id for track in tracks]))
    )
    cues_by_track: dict[int, list[ImportedAudiobookCue]] = {}
    for cue in cue_result.scalars().all():
        cues_by_track.setdefault(cue.track_id, []).append(cue)

    for track, spec in zip(tracks, materialized, strict=True):
        offset = track.source_start_ms
        if track.source_audio_file_path is None:
            track.source_audio_file_path = relative_library_path(spec.immutable_audio_path)
            track.source_clip_begin_ms = spec.immutable_start_ms
            track.source_clip_end_ms = spec.immutable_end_ms
        track.audio_file_path = relative_library_path(spec.audio_path)
        track.media_type = spec.media_type
        track.source_start_ms = spec.start_ms
        track.source_end_ms = spec.end_ms
        track.duration_ms = spec.duration_ms
        for cue in cues_by_track.get(track.id, []):
            cue.clip_begin_ms = max(0, cue.clip_begin_ms - offset)
            cue.clip_end_ms = min(spec.duration_ms, max(cue.clip_begin_ms + 1, cue.clip_end_ms - offset))

    edition.derived_revision = revision
    edition.derived_format_version = CURRENT_DERIVED_FORMAT_VERSION
    edition.progress_current = len(tracks)
    edition.progress_total = len(tracks)
    edition.progress_detail = f"Chapter audio upgraded to format v{CURRENT_DERIVED_FORMAT_VERSION}"
    edition.error = None
    await db.commit()
    cleanup_old_derived_revisions(edition_dir, revision)
    return revision


async def rebuild_imported_audiobook(
    edition_id: int,
    db: AsyncSession,
    *,
    force_assets: bool = False,
) -> HumanAudiobookRebuildResult:
    """Bring one human audiobook forward using the current complete pipeline."""
    edition = await db.get(ImportedAudiobook, edition_id)
    if edition is None:
        raise ValueError("Imported audiobook no longer exists.")
    book = await db.get(Book, edition.book_id)
    if book is None:
        raise ValueError("The selected library book no longer exists.")
    if edition.status != ImportedAudiobookStatus.READY.value:
        raise ValueError(f"Audiobook is {edition.status}, not ready to rebuild.")

    previous_alignment_method = edition.alignment_method
    needs_asset_upgrade = (
        force_assets
        or not edition.source_manifest_sha256
        or (edition.derived_format_version or 0) < CURRENT_DERIVED_FORMAT_VERSION
    )
    if needs_asset_upgrade:
        await upgrade_imported_audiobook(edition.id, db)
        await db.refresh(edition)

    result = await db.execute(
        select(ImportedAudiobookTrack)
        .where(ImportedAudiobookTrack.imported_audiobook_id == edition.id)
        .order_by(ImportedAudiobookTrack.sequence_order)
    )
    tracks = list(result.scalars().all())
    if not tracks:
        raise ValueError("Imported audiobook has no tracks to rebuild.")
    should_realign = (
        previous_alignment_method in {AlignmentMethod.TRANSCRIBED.value, AlignmentMethod.HYBRID.value}
        or bool(edition.alignment_error)
        or any(track.transcript_file_path for track in tracks)
    )

    edition.progress_current = 0
    edition.progress_total = len(tracks)
    edition.progress_detail = "Preparing current book text"
    await db.commit()
    chapters = await ensure_span_anchored_text(book, db)
    chapters_by_id = {chapter.id: chapter for chapter in chapters}

    matched_count = 0
    for index, track in enumerate(tracks, start=1):
        # Re-run automatic matching while preserving manual and legacy/unknown
        # corrections whose chapter still exists.
        if track.match_method == "automatic" or track.matched_chapter_id not in chapters_by_id:
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
            track.match_method = "automatic"
        track.alignment_score = None
        await rebuild_estimated_cues(track, db)
        matched_count += int(track.matched_chapter_id is not None)
        edition.progress_current = index
        edition.progress_detail = f"Rebuilt track {index} of {len(tracks)}"
        await db.commit()

    transition_state(
        edition,
        "alignment_method",
        ALIGNMENT_METHOD,
        AlignmentMethod.ESTIMATED,
        context=f"imported audiobook {edition.id}",
    )
    edition.pipeline_version = CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION
    edition.matched_content_version = book.content_version or 1
    edition.progress_detail = f"Rebuilt with human-audiobook pipeline v{CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION}"
    edition.error = None
    edition.alignment_error = None
    await db.commit()
    return HumanAudiobookRebuildResult(
        matched_track_count=matched_count,
        track_count=len(tracks),
        realign=should_realign,
        derived_revision=edition.derived_revision or 0,
    )


def imported_audiobook_dir(book_id: int, edition_id: int) -> Path:
    return LIBRARY_PATH / "audiobooks" / str(book_id) / "imports" / str(edition_id)


def relative_library_path(path: Path) -> str:
    return str(path.resolve().relative_to(LIBRARY_PATH.parent.resolve()))


def safe_import_filename(raw_name: str, fallback: str = "audiobook") -> str:
    name = PurePosixPath((raw_name or "").replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f/:]+", "_", name).strip(" .")
    return name or fallback


def asin_from_names(names: list[str]) -> str | None:
    """Return the Audible ASIN or ISBN-10 embedded in a Libation name."""
    for name in names:
        match = _ASIN_RE.search(name)
        if match:
            return match.group(1).upper()
    return None


@dataclass(frozen=True)
class LibationBackupGroup:
    """Supported files belonging to one Libation book directory."""

    source_key: str
    folder_name: str
    title: str
    product_id: str
    source_paths: tuple[str, ...]


def libation_backup_groups(source_paths: list[str]) -> tuple[list[LibationBackupGroup], int]:
    """Group a browser directory manifest by its ``Title [product-id]`` folder."""
    grouped: dict[str, dict[str, object]] = {}
    ignored_count = 0
    for raw_path in source_paths:
        normalized_path = (raw_path or "").replace("\\", "/").strip("/")
        path = PurePosixPath(normalized_path)
        if not normalized_path or path.suffix.lower() not in IMPORT_EXTENSIONS:
            ignored_count += 1
            continue

        folder_index = None
        folder_match = None
        for index, part in enumerate(path.parts):
            match = _ASIN_RE.search(part)
            if match:
                folder_index = index
                folder_match = match
                break
        if folder_index is None or folder_match is None:
            ignored_count += 1
            continue

        folder_name = path.parts[folder_index]
        # A ZIP can itself be named like a Libation folder. Remove the archive
        # extension for the user-facing title and stable grouping key.
        if folder_index == len(path.parts) - 1 and path.suffix.lower() == ".zip":
            folder_name = Path(folder_name).stem
        product_id = folder_match.group(1).upper()
        title = _ASIN_RE.sub("", folder_name).strip(" ._-") or "Untitled audiobook"
        source_key = "/".join((*path.parts[:folder_index], folder_name))
        entry = grouped.setdefault(
            source_key,
            {
                "folder_name": folder_name,
                "title": title,
                "product_id": product_id,
                "source_paths": [],
            },
        )
        entry["source_paths"].append(normalized_path)

    groups = [
        LibationBackupGroup(
            source_key=source_key,
            folder_name=str(entry["folder_name"]),
            title=str(entry["title"]),
            product_id=str(entry["product_id"]),
            source_paths=tuple(entry["source_paths"]),
        )
        for source_key, entry in grouped.items()
    ]
    groups.sort(key=lambda group: group.title.casefold())
    return groups, ignored_count


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


async def sentences_for_logical_chapter(
    chapter_id: int,
    db: AsyncSession,
) -> list[AudiobookSentence]:
    """Return sentences from every physical spine item in one logical chapter."""
    chapter = await db.get(AudiobookChapter, chapter_id)
    if chapter is None:
        return []
    if chapter.logical_chapter_key:
        chapter_filter = (
            AudiobookChapter.book_id == chapter.book_id,
            AudiobookChapter.logical_chapter_key == chapter.logical_chapter_key,
        )
    else:
        # Pre-migration ingestions remain readable until their next rematch.
        chapter_filter = (AudiobookChapter.id == chapter.id,)
    result = await db.execute(
        select(AudiobookSentence)
        .join(AudiobookChapter, AudiobookChapter.id == AudiobookSentence.chapter_id)
        .where(*chapter_filter)
        .order_by(
            AudiobookChapter.spine_order,
            AudiobookChapter.chapter_number,
            AudiobookSentence.sequence_order,
        )
    )
    return list(result.scalars().all())


async def rebuild_estimated_cues(track: ImportedAudiobookTrack, db: AsyncSession) -> int:
    await db.execute(delete(ImportedAudiobookCue).where(ImportedAudiobookCue.track_id == track.id))
    if track.matched_chapter_id is None:
        await db.commit()
        return 0
    sentences = await sentences_for_logical_chapter(track.matched_chapter_id, db)
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
    if not book.current_path:
        return []
    chapters = await crud.audiobook.get_chapters_for_book(db, book.id)
    content_version = book.content_version or 1
    chapters_are_current = (
        chapters
        and book.audiobook_source_content_version == content_version
        and book.audiobook_text_content_version == content_version
        and all(chapter.logical_chapter_key is not None and chapter.logical_part_order is not None for chapter in chapters)
    )
    if chapters_are_current:
        return chapters
    prior_status = book.audiobook_pipeline_status
    await ingest_epub(book.id, db)
    await db.refresh(book)
    # Importing narration must not silently opt the user into an unattended AI
    # generation run. The generated pipeline remains exactly where it was.
    transition_state(
        book,
        "audiobook_pipeline_status",
        AUDIOBOOK_PIPELINE,
        prior_status,
        context=f"book {book.id} after narration import preparation",
    )
    await db.commit()
    return await crud.audiobook.get_chapters_for_book(db, book.id)


async def process_import(edition_id: int, db: AsyncSession) -> None:
    edition = await db.get(ImportedAudiobook, edition_id)
    if edition is None:
        return
    transition_state(
        edition,
        "status",
        IMPORTED_AUDIOBOOK,
        ImportedAudiobookStatus.IMPORTING,
        context=f"imported audiobook {edition.id}",
    )
    edition.error = None
    edition.progress_detail = "Inspecting uploaded files"
    await db.commit()
    try:
        book = await db.get(Book, edition.book_id)
        if book is None:
            raise ValueError("The selected library book no longer exists.")
        edition_dir = imported_audiobook_dir(book.id, edition.id)
        audio_paths, cue_paths = _prepare_sources(edition_dir)
        await enrich_audio_only_book(book, edition, audio_paths, cue_paths, db)
        specs, duration_ms = await _track_specs(audio_paths, cue_paths)
        manifest_path, manifest_sha, source_size = await build_source_manifest(edition, edition_dir)
        edition.source_manifest_file_path = relative_library_path(manifest_path)
        edition.source_manifest_sha256 = manifest_sha
        edition.source_size_bytes = source_size
        edition.progress_total = len(specs)
        edition.progress_current = 0
        edition.progress_detail = "Preparing chapter audio files"
        await db.commit()
        revision = _next_derived_revision(edition, edition_dir)

        async def update_progress(current: int, total: int) -> None:
            edition.progress_current = current
            edition.progress_total = total
            edition.progress_detail = f"Building chapter audio {current} of {total}"
            await db.commit()

        specs = await _materialize_chapter_audio(specs, edition_dir, revision, update_progress)
        edition.duration_ms = duration_ms
        edition.source_type = "libation" if cue_paths or edition.asin else "upload"
        edition.progress_total = len(specs)
        edition.progress_current = 0
        edition.progress_detail = "Preparing synchronized book text" if book.current_path else "Preparing audio tracks"
        await db.commit()

        chapters = await ensure_span_anchored_text(book, db)
        await db.execute(delete(ImportedAudiobookTrack).where(ImportedAudiobookTrack.imported_audiobook_id == edition.id))
        await db.commit()
        for index, spec in enumerate(specs, start=1):
            matched = _chapter_match(spec, chapters)
            track = ImportedAudiobookTrack(
                imported_audiobook_id=edition.id,
                matched_chapter_id=matched.id if matched else None,
                match_method="automatic",
                sequence_order=spec.sequence_order,
                title=spec.title,
                audio_file_path=relative_library_path(spec.audio_path),
                media_type=spec.media_type,
                source_audio_file_path=relative_library_path(spec.immutable_audio_path),
                source_clip_begin_ms=spec.immutable_start_ms,
                source_clip_end_ms=spec.immutable_end_ms,
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
        transition_state(
            edition,
            "status",
            IMPORTED_AUDIOBOOK,
            ImportedAudiobookStatus.READY,
            context=f"imported audiobook {edition.id}",
        )
        transition_state(
            edition,
            "alignment_method",
            ALIGNMENT_METHOD,
            AlignmentMethod.ESTIMATED,
            context=f"imported audiobook {edition.id}",
        )
        edition.matched_content_version = book.content_version or 1
        edition.derived_revision = revision
        edition.derived_format_version = CURRENT_DERIVED_FORMAT_VERSION
        edition.pipeline_version = CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION
        edition.progress_current = len(specs)
        edition.progress_total = len(specs)
        edition.progress_detail = (
            f"Ready: {matched_count} of {len(specs)} tracks matched"
            if book.current_path
            else f"Ready: {len(specs)} audio-only tracks"
        )
        edition.error = None
        if not book.current_path:
            book.content_updated_at = datetime.now(timezone.utc)
        await db.commit()
        cleanup_old_derived_revisions(edition_dir, revision)
        shutil.rmtree(edition_dir / "incoming", ignore_errors=True)
        await queue_audio_metadata_lookup(book, db)
    except Exception as exc:
        logger.exception("Audiobook import %s failed.", edition_id)
        await db.rollback()
        edition = await db.get(ImportedAudiobook, edition_id)
        if edition is not None:
            transition_state(
                edition,
                "status",
                IMPORTED_AUDIOBOOK,
                ImportedAudiobookStatus.ERROR,
                context=f"imported audiobook {edition.id}",
            )
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

    transition_state(
        edition,
        "status",
        IMPORTED_AUDIOBOOK,
        ImportedAudiobookStatus.IMPORTING,
        context=f"imported audiobook {edition.id}",
    )
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
        track.match_method = "automatic"
        track.alignment_score = None
        await db.commit()
        await rebuild_estimated_cues(track, db)
        matched_count += int(matched is not None)
        edition.progress_current = index
        edition.progress_detail = f"Rematched track {index} of {len(tracks)}"
        await db.commit()

    transition_state(
        edition,
        "status",
        IMPORTED_AUDIOBOOK,
        ImportedAudiobookStatus.READY,
        context=f"imported audiobook {edition.id}",
    )
    transition_state(
        edition,
        "alignment_method",
        ALIGNMENT_METHOD,
        AlignmentMethod.ESTIMATED,
        context=f"imported audiobook {edition.id}",
    )
    edition.matched_content_version = book.content_version or 1
    edition.pipeline_version = CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION
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
    track.match_method = "manual"
    track.alignment_score = None
    edition = await db.get(ImportedAudiobook, track.imported_audiobook_id)
    if edition is not None:
        transition_state(
            edition,
            "alignment_method",
            ALIGNMENT_METHOD,
            AlignmentMethod.ESTIMATED,
            context=f"imported audiobook {edition.id}",
        )
        edition.alignment_error = None
    await db.commit()
    await db.refresh(track)
    return await rebuild_estimated_cues(track, db)
