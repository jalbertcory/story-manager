"""Receive human-narrated audiobook uploads and hand them to the processing queue."""

from __future__ import annotations

import asyncio
import shutil

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ..job_payloads import ImportAudiobookPayload
from ..lifecycle import IMPORTED_AUDIOBOOK, ImportedAudiobookStatus, transition_state
from ..models import ImportedAudiobook
from . import audiobook_import
from .audiobook_import import asin_from_names, display_name_from_filename, safe_import_filename
from .processing_queue import queue_processing_job


async def receive_audiobook_upload(
    db: AsyncSession,
    *,
    book_id: int,
    files: list[UploadFile],
    name: str | None,
    source_paths: list[str],
    auto_align: bool,
) -> ImportedAudiobook:
    """Stream ``files`` into a new edition's staging folder and queue its import.

    On failure the edition is marked as errored and the original exception is
    re-raised; ``AudiobookUploadTooLargeError`` signals the size limit.
    """
    filenames = [file.filename or "" for file in files]
    display_names = source_paths if len(source_paths) == len(files) else filenames
    edition = ImportedAudiobook(
        book_id=book_id,
        name=(name or "").strip() or display_name_from_filename(display_names[0]),
        asin=asin_from_names(display_names),
        status="queued",
        original_filenames=display_names,
        progress_detail="Receiving upload",
    )
    db.add(edition)
    await db.commit()
    await db.refresh(edition)
    incoming_dir = audiobook_import.imported_audiobook_dir(book_id, edition.id) / "incoming"
    remaining = audiobook_import.MAX_AUDIOBOOK_UPLOAD_BYTES
    upload_complete = False
    try:
        for upload in files:
            destination = incoming_dir / safe_import_filename(upload.filename or "audiobook")
            if destination.exists():
                destination = incoming_dir / f"{destination.stem}-{len(list(incoming_dir.glob('*'))) + 1}{destination.suffix}"
            written = await audiobook_import.stream_upload_to_path(upload, destination, remaining)
            remaining -= written
        upload_complete = True
        edition.progress_detail = "Queued for import"
        await db.commit()
        await queue_processing_job(
            db=db,
            job_type="import_audiobook",
            book_id=book_id,
            target_type="imported_audiobook",
            target_id=edition.id,
            payload=ImportAudiobookPayload(auto_align=auto_align),
            dedupe_key=f"import_audiobook:imported_audiobook:{edition.id}",
            progress_detail="Queued after audiobook upload",
        )
    except Exception as exc:
        transition_state(
            edition,
            "status",
            IMPORTED_AUDIOBOOK,
            ImportedAudiobookStatus.ERROR,
            context=f"imported audiobook {edition.id}",
        )
        edition.error = str(exc)
        edition.progress_detail = "Upload failed"
        if not upload_complete:
            # Discard files from an interrupted multi-file upload so a retry
            # cannot import an incomplete set of tracks as the whole book.
            await asyncio.to_thread(shutil.rmtree, incoming_dir, ignore_errors=True)
            incoming_dir.mkdir(parents=True, exist_ok=True)
        await db.commit()
        raise
    return edition
