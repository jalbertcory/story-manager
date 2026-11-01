"""Storage cleanup must not delete files that are still being written or are about to be tracked."""

import os
import time

import pytest

from backend.app import crud, models
from backend.app.routers import storage
from backend.app.services import web_novel


@pytest.fixture
def library(tmp_path, monkeypatch):
    library = (tmp_path / "library").resolve()
    library.mkdir()
    monkeypatch.setattr(storage, "LIBRARY_PATH", library)
    return library


def write_aged(path, age_seconds, data=b"data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    mtime = time.time() - age_seconds
    os.utime(path, (mtime, mtime))
    return path


def cleanup(app_client, dry_run):
    response = app_client.post(f"/api/storage/cleanup?dry_run={str(dry_run).lower()}")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_cleanup_only_deletes_old_untracked_files(app_client, library):
    old = storage.RECENT_FILE_GRACE_SECONDS * 2
    orphan = write_aged(library / "Author" / "Old Orphan.epub", old)
    fresh = write_aged(library / "Author" / "Just Uploaded.epub", 5)
    atomic_temp = write_aged(library / "Author" / ".Book.epub.abc123", old)
    stale_staging = write_aged(library / ".staging" / "tmp_abc_upload.epub", storage.STALE_STAGING_SECONDS * 2)
    active_staging = write_aged(library / ".staging" / "fff-xyz" / "Story.epub", old)

    preview = cleanup(app_client, dry_run=True)
    assert sorted(f["path"] for f in preview["files"]) == [
        "library/.staging/tmp_abc_upload.epub",
        "library/Author/Old Orphan.epub",
    ]

    cleanup(app_client, dry_run=False)
    assert not orphan.exists()
    assert not stale_staging.exists()
    assert fresh.exists()
    assert atomic_temp.exists()
    assert active_staging.exists()


@pytest.mark.asyncio
async def test_cleanup_refuses_while_book_is_refreshing(app_client, db, library):
    orphan = write_aged(library / "orphan.epub", storage.RECENT_FILE_GRACE_SECONDS * 2)
    db.add(
        models.Book(
            title="Story",
            author="Author",
            source_type=models.SourceType.web,
            source_url="https://example.com/s/1",
            refresh_status="processing",
        )
    )
    await db.commit()

    result = cleanup(app_client, dry_run=False)

    assert "refreshing" in result["skipped_reason"]
    assert orphan.exists()


@pytest.mark.asyncio
async def test_cleanup_refuses_while_processing_job_is_active(app_client, db, library):
    orphan = write_aged(library / "orphan.epub", storage.RECENT_FILE_GRACE_SECONDS * 2)
    await crud.create_processing_job(db, job_type="clean_book", resource_lane="cpu")
    await db.commit()

    result = cleanup(app_client, dry_run=False)

    assert "processing job" in result["skipped_reason"]
    assert orphan.exists()


@pytest.mark.asyncio
async def test_cleanup_refuses_while_fanficfare_runs(app_client, library):
    orphan = write_aged(library / "orphan.epub", storage.RECENT_FILE_GRACE_SECONDS * 2)

    async with web_novel._fff_lock:
        result = cleanup(app_client, dry_run=False)

    assert "web novel" in result["skipped_reason"]
    assert orphan.exists()
