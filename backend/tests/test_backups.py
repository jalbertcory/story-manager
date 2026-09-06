"""Backup archive, restore safety, and API coverage."""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from backend.app import backup_cli
from backend.app.routers import backups as backups_router
from backend.app.services import backups
from backend.app.services.backup_barrier import BackupBarrier, BackupInProgressError


def _fake_database_dump(_database_url: str, destination: Path, _pg_dump_path: str | None = None) -> None:
    destination.write_bytes(b"PGDMP-test-database")


def _create_archive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    library = tmp_path / "library"
    library.mkdir()
    (library / "book.epub").write_bytes(b"epub data")
    (library / "audiobooks").mkdir()
    (library / "audiobooks" / "chapter.mp3").write_bytes(b"audio data")
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(backups, "_dump_database", _fake_database_dump)
    summary = backups.create_backup_archive(
        database_url="postgresql+psycopg://storyuser:secret@localhost/story_manager",
        library_path=library,
        backup_path=backup_dir,
    )
    return backup_dir / str(summary["filename"]), library


def test_create_and_verify_backup_archive(monkeypatch, tmp_path):
    archive, _library = _create_archive(monkeypatch, tmp_path)

    manifest = backups.verify_backup_archive(archive)
    summary = backups.backup_summary(archive)

    assert manifest["format"] == backups.BACKUP_FORMAT
    assert manifest["library"] == {"path": "library/", "file_count": 2, "size_bytes": 19}
    assert summary["valid_manifest"] is True
    assert summary["verified_at_creation"] is True
    assert summary["library_file_count"] == 2
    assert archive.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("manifest_json", ["null", "[]", '"text"', "42"])
def test_verification_and_listing_reject_non_object_manifest(tmp_path, manifest_json):
    archive = tmp_path / "invalid.story-manager.zip"
    with zipfile.ZipFile(archive, "w") as destination:
        destination.writestr(backups.MANIFEST_NAME, manifest_json)

    with pytest.raises(backups.BackupError, match="manifest is invalid"):
        backups.verify_backup_archive(archive)
    summary = backups.backup_summary(archive)
    assert summary["valid_manifest"] is False
    assert summary["error"] == "Backup manifest is invalid."


def test_verification_rejects_changed_file(monkeypatch, tmp_path):
    archive, _library = _create_archive(monkeypatch, tmp_path)
    changed = tmp_path / "changed.story-manager.zip"
    with zipfile.ZipFile(archive, "r") as source, zipfile.ZipFile(changed, "w") as destination:
        for info in source.infolist():
            data = source.read(info)
            if info.filename == "library/book.epub":
                data += b"tampered"
            destination.writestr(info.filename, data)

    with pytest.raises(backups.BackupError, match="size check failed"):
        backups.verify_backup_archive(changed)


def test_verification_rejects_unsafe_or_undeclared_paths(monkeypatch, tmp_path):
    archive, _library = _create_archive(monkeypatch, tmp_path)
    changed = tmp_path / "unsafe.story-manager.zip"
    shutil.copyfile(archive, changed)
    with zipfile.ZipFile(changed, "a") as destination:
        destination.writestr("../outside.txt", b"unsafe")

    with pytest.raises(backups.BackupError, match="unsafe paths"):
        backups.verify_backup_archive(changed)


def test_backup_directory_must_not_be_inside_library(monkeypatch, tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setattr(backups, "_dump_database", _fake_database_dump)
    with pytest.raises(backups.BackupError, match="outside the library"):
        backups.create_backup_archive(
            database_url="postgresql+psycopg://storyuser:secret@localhost/story_manager",
            library_path=library,
            backup_path=library / "backups",
        )


def test_database_dump_can_use_development_postgres_container(monkeypatch, tmp_path):
    destination = tmp_path / "database.dump"
    monkeypatch.setenv("STORY_MANAGER_PG_DUMP_CONTAINER", "story-manager-db")
    monkeypatch.setattr(backups, "_find_postgres_tool", lambda *_args: (_ for _ in ()).throw(backups.BackupError()))
    monkeypatch.setattr(backups.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)

    def run(args, *, stdout, stderr, check):
        assert args[:5] == ["/usr/bin/docker", "exec", "-i", "story-manager-db", "pg_dump"]
        assert "secret" not in args
        stdout.write(b"PGDMP-container")
        return subprocess.CompletedProcess(args, 0, stderr=b"")

    monkeypatch.setattr(backups.subprocess, "run", run)
    backups._dump_database(
        "postgresql+psycopg://storyuser:secret@localhost/story_manager",
        destination,
    )

    assert destination.read_bytes() == b"PGDMP-container"


def test_retention_prunes_only_oldest_managed_archives(tmp_path):
    archives = []
    for index in range(3):
        archive = tmp_path / f"backup-{index}.story-manager.zip"
        archive.write_bytes(b"backup")
        os.utime(archive, ns=(index + 1, index + 1))
        archives.append(archive)
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("keep")

    removed = backups.prune_backups(tmp_path, retention_count=2)

    assert removed == [archives[0]]
    assert not archives[0].exists()
    assert archives[1].exists() and archives[2].exists()
    assert unrelated.exists()


def test_restore_replaces_library_after_database_restore(monkeypatch, tmp_path):
    archive, source_library = _create_archive(monkeypatch, tmp_path)
    source_library.rename(tmp_path / "source-library")
    library = tmp_path / "library"
    library.mkdir()
    (library / "old.epub").write_bytes(b"old")
    monkeypatch.setattr(backups, "_run_postgres_tool", lambda *_args: None)

    backups.restore_backup_archive(
        archive_path=archive,
        database_url="postgresql+psycopg://storyuser:secret@localhost/story_manager",
        library_path=library,
        pg_restore_path=shutil.which("true"),
    )

    assert (library / "book.epub").read_bytes() == b"epub data"
    assert (library / "audiobooks" / "chapter.mp3").read_bytes() == b"audio data"
    assert not (library / "old.epub").exists()


def test_restore_rolls_library_back_when_database_restore_fails(monkeypatch, tmp_path):
    archive, source_library = _create_archive(monkeypatch, tmp_path)
    source_library.rename(tmp_path / "source-library")
    library = tmp_path / "library"
    library.mkdir()
    (library / "old.epub").write_bytes(b"old")

    def fail_restore(*_args):
        raise backups.BackupError("database restore failed")

    monkeypatch.setattr(backups, "_run_postgres_tool", fail_restore)
    with pytest.raises(backups.BackupError, match="database restore failed"):
        backups.restore_backup_archive(
            archive_path=archive,
            database_url="postgresql+psycopg://storyuser:secret@localhost/story_manager",
            library_path=library,
            pg_restore_path=shutil.which("true"),
        )

    assert (library / "old.epub").read_bytes() == b"old"
    assert not (library / "book.epub").exists()


@pytest.mark.asyncio
async def test_backup_barrier_blocks_new_mutations_and_waits_for_existing_one():
    barrier = BackupBarrier()
    mutation = barrier.mutation()
    await mutation.__aenter__()
    entered = False

    async def enter_backup():
        nonlocal entered
        async with barrier.backup():
            entered = True

    import asyncio

    task = asyncio.create_task(enter_backup())
    await asyncio.sleep(0)
    assert barrier.backup_active is True
    assert entered is False
    with pytest.raises(BackupInProgressError):
        async with barrier.mutation():
            pass
    await mutation.__aexit__(None, None, None)
    await task
    assert entered is True
    assert barrier.backup_active is False


def test_backup_api_lists_downloads_queues_and_deletes(app_client, monkeypatch, tmp_path):
    archive, _library = _create_archive(monkeypatch, tmp_path)
    monkeypatch.setattr(backups_router, "BACKUP_PATH", archive.parent)

    listed = app_client.get("/api/backups")
    assert listed.status_code == 200
    assert listed.json()["retention_count"] == 10
    assert listed.json()["backups"][0]["filename"] == archive.name

    create_response = app_client.post("/api/backups")
    assert create_response.status_code == 202
    assert create_response.json()["job_type"] == "create_backup"

    verify_response = app_client.post(f"/api/backups/{archive.name}/verify")
    assert verify_response.status_code == 202
    assert verify_response.json()["job_type"] == "verify_backup"
    assert verify_response.json()["payload"] == {"filename": archive.name}

    download = app_client.get(f"/api/backups/{archive.name}/download")
    assert download.status_code == 200
    assert download.content == archive.read_bytes()

    deleted = app_client.delete(f"/api/backups/{archive.name}")
    assert deleted.status_code == 204
    assert not archive.exists()


def test_backup_api_rejects_path_traversal(app_client, monkeypatch, tmp_path):
    monkeypatch.setattr(backups_router, "BACKUP_PATH", tmp_path)
    response = app_client.get("/api/backups/not-a-backup/download")
    assert response.status_code == 404


def test_restore_cli_requires_explicit_confirmation(capsys, tmp_path):
    result = backup_cli.main(["restore", str(tmp_path / "backup.story-manager.zip")])
    assert result == 2
    assert "--confirm-replace" in capsys.readouterr().err
