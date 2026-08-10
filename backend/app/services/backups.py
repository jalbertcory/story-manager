"""Create, inspect, verify, and restore portable Story Manager backups."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy.engine import URL, make_url

BACKUP_FORMAT = "story-manager-backup"
BACKUP_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
DATABASE_DUMP_NAME = "database.dump"
BACKUP_SUFFIX = ".story-manager.zip"
_COPY_CHUNK_SIZE = 1024 * 1024


class BackupError(RuntimeError):
    """A safe, user-facing backup or restore failure."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _find_postgres_tool(name: str, configured_path: str | None = None) -> str:
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        raise BackupError(f"Configured {name} executable was not found: {candidate}")

    discovered = shutil.which(name)
    if discovered:
        return discovered

    candidates = sorted(Path("/usr/lib/postgresql").glob(f"*/bin/{name}"), reverse=True)
    if candidates:
        return str(candidates[0])
    raise BackupError(f"{name} is required but was not found. Install PostgreSQL client tools and try again.")


def _postgres_connection(database_url: str) -> tuple[URL, dict[str, str]]:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql" or not url.database:
        raise BackupError("Backup and restore require a PostgreSQL DATABASE_URL.")
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    return url, env


def _connection_args(url: URL) -> list[str]:
    args: list[str] = []
    if url.host:
        args.extend(("--host", url.host))
    if url.port:
        args.extend(("--port", str(url.port)))
    if url.username:
        args.extend(("--username", url.username))
    args.extend(("--dbname", url.database or ""))
    return args


def _run_postgres_tool(args: list[str], env: dict[str, str], operation: str) -> None:
    result = subprocess.run(args, env=env, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "unknown PostgreSQL error").strip()
    raise BackupError(f"{operation} failed: {detail}")


def _dump_database(database_url: str, destination: Path, pg_dump_path: str | None = None) -> None:
    url, env = _postgres_connection(database_url)
    try:
        executable = _find_postgres_tool("pg_dump", pg_dump_path or os.getenv("STORY_MANAGER_PG_DUMP_PATH"))
    except BackupError:
        container = os.getenv("STORY_MANAGER_PG_DUMP_CONTAINER")
        if not container:
            raise
        _dump_database_from_container(url, destination, container)
        return
    args = [
        executable,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(destination),
        *_connection_args(url),
    ]
    _run_postgres_tool(args, env, "Database backup")


def _dump_database_from_container(url: URL, destination: Path, container: str) -> None:
    """Use the project's development PostgreSQL container when client tools are absent."""
    docker = shutil.which("docker")
    if not docker:
        raise BackupError("Docker is required to use the configured PostgreSQL dump container.")
    args = [docker, "exec", "-i", container, "pg_dump", "--format=custom", "--no-owner", "--no-privileges"]
    if url.username:
        args.extend(("--username", url.username))
    args.extend(("--dbname", url.database or ""))
    with destination.open("wb") as output:
        result = subprocess.run(args, stdout=output, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        destination.unlink(missing_ok=True)
        detail = (result.stderr or b"unknown PostgreSQL error").decode("utf-8", errors="replace").strip()
        raise BackupError(f"Database backup failed: {detail}")


def _sha256_stream(source: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := source.read(_COPY_CHUNK_SIZE):
        digest.update(chunk)
    return digest.hexdigest()


def _write_file(archive: zipfile.ZipFile, source: Path, archive_name: str) -> dict[str, object]:
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as input_file, archive.open(archive_name, "w", force_zip64=True) as output_file:
        while chunk := input_file.read(_COPY_CHUNK_SIZE):
            output_file.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return {"path": archive_name, "size_bytes": size, "sha256": digest.hexdigest()}


def _library_files(library_path: Path) -> list[Path]:
    if not library_path.exists():
        return []
    files: list[Path] = []
    for candidate in library_path.rglob("*"):
        if candidate.is_symlink():
            raise BackupError(f"Library backups do not follow symbolic links: {candidate}")
        if candidate.is_file():
            files.append(candidate)
    return sorted(files, key=lambda item: item.relative_to(library_path).as_posix())


def create_backup_archive(
    *,
    database_url: str,
    library_path: Path,
    backup_path: Path,
    pg_dump_path: str | None = None,
    retention_count: int = 10,
) -> dict[str, object]:
    """Create and verify an archive, publishing it atomically when complete."""
    created_at = _utc_now()
    if backup_path.resolve().is_relative_to(library_path.resolve()):
        raise BackupError("The backup directory must be outside the library directory.")
    backup_path.mkdir(parents=True, exist_ok=True)
    filename = f"story-manager-{created_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}{BACKUP_SUFFIX}"
    destination = backup_path / filename

    with tempfile.TemporaryDirectory(prefix="story-manager-backup-", dir=backup_path) as temp_name:
        temp_dir = Path(temp_name)
        database_dump = temp_dir / DATABASE_DUMP_NAME
        archive_path = temp_dir / filename
        _dump_database(database_url, database_dump, pg_dump_path)

        file_entries: list[dict[str, object]] = []
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            file_entries.append(_write_file(archive, database_dump, DATABASE_DUMP_NAME))
            for source in _library_files(library_path):
                relative = source.relative_to(library_path).as_posix()
                file_entries.append(_write_file(archive, source, f"library/{relative}"))

            library_entries = [entry for entry in file_entries if str(entry["path"]).startswith("library/")]
            manifest = {
                "format": BACKUP_FORMAT,
                "format_version": BACKUP_FORMAT_VERSION,
                "created_at": created_at.isoformat(),
                "integrity": {"algorithm": "sha256", "verified_at_creation": True},
                "database": {"path": DATABASE_DUMP_NAME, "format": "postgresql-custom"},
                "library": {
                    "path": "library/",
                    "file_count": len(library_entries),
                    "size_bytes": sum(int(entry["size_bytes"]) for entry in library_entries),
                },
                "files": file_entries,
            }
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))

        verify_backup_archive(archive_path)
        os.chmod(archive_path, 0o600)
        os.replace(archive_path, destination)

    prune_backups(backup_path, retention_count=retention_count)
    return backup_summary(destination)


def _safe_archive_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def _load_manifest(archive: zipfile.ZipFile) -> dict[str, object]:
    try:
        info = archive.getinfo(MANIFEST_NAME)
    except KeyError as exc:
        raise BackupError("Backup manifest is missing.") from exc
    if info.file_size > 64 * 1024 * 1024:
        raise BackupError("Backup manifest is unexpectedly large.")
    try:
        manifest = json.loads(archive.read(info))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackupError("Backup manifest is invalid.") from exc
    if manifest.get("format") != BACKUP_FORMAT or manifest.get("format_version") != BACKUP_FORMAT_VERSION:
        raise BackupError("This backup format is not supported by this Story Manager version.")
    return manifest


def verify_backup_archive(archive_path: Path) -> dict[str, object]:
    """Validate archive layout, declared sizes, and every SHA-256 checksum."""
    if not archive_path.is_file():
        raise BackupError(f"Backup archive was not found: {archive_path}")
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or any(not _safe_archive_name(name) for name in names):
                raise BackupError("Backup contains duplicate or unsafe paths.")
            if any(info.compress_type != zipfile.ZIP_STORED for info in infos):
                raise BackupError("Backup uses an unsupported compression method.")
            manifest = _load_manifest(archive)
            raw_entries = manifest.get("files")
            if not isinstance(raw_entries, list):
                raise BackupError("Backup manifest has no file inventory.")

            expected_names = {MANIFEST_NAME}
            for entry in raw_entries:
                if not isinstance(entry, dict):
                    raise BackupError("Backup manifest contains an invalid file entry.")
                name = entry.get("path")
                size = entry.get("size_bytes")
                expected_hash = entry.get("sha256")
                if not isinstance(name, str) or not _safe_archive_name(name):
                    raise BackupError("Backup manifest contains an unsafe path.")
                if not isinstance(size, int) or size < 0 or not isinstance(expected_hash, str):
                    raise BackupError(f"Backup manifest metadata is invalid for {name}.")
                try:
                    info = archive.getinfo(name)
                except KeyError as exc:
                    raise BackupError(f"Backup is missing {name}.") from exc
                if info.file_size != size:
                    raise BackupError(f"Backup size check failed for {name}.")
                with archive.open(info, "r") as source:
                    actual_hash = _sha256_stream(source)
                if actual_hash != expected_hash:
                    raise BackupError(f"Backup checksum failed for {name}.")
                expected_names.add(name)
            if set(names) != expected_names:
                raise BackupError("Backup contains files that are not declared in its manifest.")
            if DATABASE_DUMP_NAME not in expected_names:
                raise BackupError("Backup database dump is missing.")
            return manifest
    except zipfile.BadZipFile as exc:
        raise BackupError("Backup archive is not a readable ZIP file.") from exc


def backup_summary(archive_path: Path) -> dict[str, object]:
    stat = archive_path.stat()
    summary: dict[str, object] = {
        "filename": archive_path.name,
        "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        "size_bytes": stat.st_size,
        "library_file_count": 0,
        "library_size_bytes": 0,
        "valid_manifest": False,
        "verified_at_creation": False,
        "error": None,
        "download_url": f"/api/backups/{archive_path.name}/download",
    }
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            manifest = _load_manifest(archive)
        library = manifest.get("library") if isinstance(manifest.get("library"), dict) else {}
        integrity = manifest.get("integrity") if isinstance(manifest.get("integrity"), dict) else {}
        created_at = datetime.fromisoformat(str(manifest["created_at"]))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        summary.update(
            {
                "created_at": created_at,
                "library_file_count": int(library.get("file_count", 0)),
                "library_size_bytes": int(library.get("size_bytes", 0)),
                "valid_manifest": True,
                "verified_at_creation": bool(integrity.get("verified_at_creation")),
            }
        )
    except (BackupError, KeyError, TypeError, ValueError, zipfile.BadZipFile) as exc:
        summary["error"] = str(exc)
    return summary


def list_backups(backup_path: Path) -> list[dict[str, object]]:
    if not backup_path.exists():
        return []
    archives = [item for item in backup_path.iterdir() if item.is_file() and item.name.endswith(BACKUP_SUFFIX)]
    return sorted((backup_summary(item) for item in archives), key=lambda item: item["created_at"], reverse=True)


def prune_backups(backup_path: Path, *, retention_count: int) -> list[Path]:
    """Delete oldest managed archives beyond the configured count; zero keeps all."""
    if retention_count <= 0 or not backup_path.exists():
        return []
    archives = sorted(
        (item for item in backup_path.iterdir() if item.is_file() and item.name.endswith(BACKUP_SUFFIX)),
        key=lambda item: (item.stat().st_mtime_ns, item.name),
        reverse=True,
    )
    removed = archives[retention_count:]
    for archive in removed:
        archive.unlink()
    return removed


def resolve_backup(backup_path: Path, filename: str) -> Path:
    if Path(filename).name != filename or not filename.endswith(BACKUP_SUFFIX):
        raise BackupError("Invalid backup filename.")
    resolved_root = backup_path.resolve()
    candidate = (resolved_root / filename).resolve()
    if not candidate.is_relative_to(resolved_root) or not candidate.is_file():
        raise BackupError("Backup archive was not found.")
    return candidate


def restore_backup_archive(
    *,
    archive_path: Path,
    database_url: str,
    library_path: Path,
    pg_restore_path: str | None = None,
) -> None:
    """Restore verified files and the database, rolling files back if PostgreSQL fails."""
    manifest = verify_backup_archive(archive_path)
    url, env = _postgres_connection(database_url)
    executable = _find_postgres_tool("pg_restore", pg_restore_path or os.getenv("STORY_MANAGER_PG_RESTORE_PATH"))
    library_path.mkdir(parents=True, exist_ok=True)

    # The production library is a bind mount, so its mount point cannot be
    # renamed. Stage and roll back entries inside that same filesystem.
    with tempfile.TemporaryDirectory(prefix=".story-manager-restore-", dir=library_path) as temp_name:
        temp_dir = Path(temp_name)
        staged_library = temp_dir / "library"
        staged_library.mkdir()
        previous_library = temp_dir / "previous-library"
        previous_library.mkdir()
        database_dump = temp_dir / DATABASE_DUMP_NAME
        with zipfile.ZipFile(archive_path, "r") as archive:
            for entry in manifest["files"]:
                name = str(entry["path"])
                if name == DATABASE_DUMP_NAME:
                    destination = database_dump
                elif name.startswith("library/"):
                    destination = staged_library / PurePosixPath(name).relative_to("library")
                else:
                    raise BackupError(f"Backup contains an unsupported entry: {name}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=_COPY_CHUNK_SIZE)

        previous_entries = [entry for entry in library_path.iterdir() if entry != temp_dir]
        restored_entries: list[Path] = []

        def roll_back_library() -> None:
            for entry in reversed(restored_entries):
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry)
                else:
                    entry.unlink(missing_ok=True)
            for entry in previous_library.iterdir():
                entry.rename(library_path / entry.name)

        try:
            for entry in previous_entries:
                entry.rename(previous_library / entry.name)
            for entry in list(staged_library.iterdir()):
                destination = library_path / entry.name
                entry.rename(destination)
                restored_entries.append(destination)
            args = [
                executable,
                "--exit-on-error",
                "--single-transaction",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                *_connection_args(url),
                str(database_dump),
            ]
            _run_postgres_tool(args, env, "Database restore")
        except Exception:
            roll_back_library()
            raise
