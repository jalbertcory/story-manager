"""centralize lifecycle values with database constraints

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-09 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

CONSTRAINTS = {
    "books": {
        "ck_books_download_status": ("download_status", ("pending", "error")),
        "ck_books_refresh_status": ("refresh_status", ("queued", "processing", "error")),
        "ck_books_audiobook_pipeline_status": (
            "audiobook_pipeline_status",
            ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling", "paused", "complete", "error"),
        ),
        "ck_books_audiobook_publication_state": (
            "audiobook_publication_state",
            ("processing", "partial", "complete", "stale", "error"),
        ),
    },
    "processing_jobs": {
        "ck_processing_jobs_status": ("status", ("queued", "running", "completed", "error", "canceled")),
    },
    "update_tasks": {
        "ck_update_tasks_status": ("status", ("running", "completed", "failed", "interrupted")),
    },
    "metadata_sync_jobs": {
        "ck_metadata_sync_jobs_status": ("status", ("queued", "running", "completed", "failed")),
    },
    "audiobook_chapters": {
        "ck_audiobook_chapters_preview_status": ("preview_status", ("queued", "generating", "ready", "error")),
        "ck_audiobook_chapters_generation_state": ("generation_state", ("pending", "processing", "ready", "error")),
    },
    "audiobook_sentences": {
        "ck_audiobook_sentences_status": (
            "status",
            ("pending_diarization", "ready_for_audio", "audio_queued", "audio_generating", "audio_generated", "error"),
        ),
    },
    "imported_audiobooks": {
        "ck_imported_audiobooks_status": ("status", ("queued", "importing", "ready", "aligning", "stale", "error")),
        "ck_imported_audiobooks_alignment_method": (
            "alignment_method",
            ("estimated", "transcribed", "hybrid"),
        ),
    },
}


def _table(conn, name: str, columns: dict[str, sa.types.TypeEngine]) -> sa.TableClause:
    return sa.table(name, *(sa.column(column_name, column_type) for column_name, column_type in columns.items()))


def _normalize_existing_values(conn) -> None:
    if sa.inspect(conn).has_table("books"):
        books = _table(
            conn,
            "books",
            {
                "download_status": sa.String(),
                "refresh_status": sa.String(),
                "audiobook_pipeline_status": sa.String(),
                "audiobook_publication_state": sa.String(),
                "audiobook_publication_error": sa.Text(),
            },
        )
        conn.execute(books.update().where(books.c.download_status == "complete").values(download_status=None))
        conn.execute(books.update().where(books.c.download_status == "processing").values(download_status="pending"))
        conn.execute(
            books.update()
            .where(
                books.c.download_status.is_not(None),
                books.c.download_status.not_in(("pending", "error")),
            )
            .values(download_status="error")
        )
        conn.execute(
            books.update()
            .where(books.c.refresh_status.is_not(None), books.c.refresh_status.not_in(("queued", "processing", "error")))
            .values(refresh_status="error")
        )
        conn.execute(
            books.update()
            .where(
                books.c.audiobook_pipeline_status.is_not(None),
                books.c.audiobook_pipeline_status.not_in(
                    ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling", "paused", "complete", "error")
                ),
            )
            .values(audiobook_pipeline_status="error")
        )
        conn.execute(
            books.update()
            .where(
                books.c.audiobook_publication_state.is_not(None),
                books.c.audiobook_publication_state.not_in(("processing", "partial", "complete", "stale", "error")),
            )
            .values(
                audiobook_publication_state="error",
                audiobook_publication_error="Unsupported publication state repaired by migration 0033.",
            )
        )

    repairs = (
        ("processing_jobs", "status", ("queued", "running", "completed", "error", "canceled"), "error"),
        ("update_tasks", "status", ("running", "completed", "failed", "interrupted"), "interrupted"),
        ("metadata_sync_jobs", "status", ("queued", "running", "completed", "failed"), "failed"),
        (
            "audiobook_sentences",
            "status",
            ("pending_diarization", "ready_for_audio", "audio_queued", "audio_generating", "audio_generated", "error"),
            "error",
        ),
        ("imported_audiobooks", "status", ("queued", "importing", "ready", "aligning", "stale", "error"), "error"),
    )
    inspector = sa.inspect(conn)
    for table_name, column_name, valid, replacement in repairs:
        if not inspector.has_table(table_name):
            continue
        table = _table(conn, table_name, {column_name: sa.String()})
        conn.execute(table.update().where(table.c[column_name].not_in(valid)).values({column_name: replacement}))

    if inspector.has_table("audiobook_chapters"):
        chapters = _table(
            conn,
            "audiobook_chapters",
            {"preview_status": sa.String(), "preview_error": sa.Text(), "generation_state": sa.String()},
        )
        conn.execute(
            chapters.update()
            .where(
                chapters.c.preview_status.is_not(None),
                chapters.c.preview_status.not_in(("queued", "generating", "ready", "error")),
            )
            .values(preview_status="error", preview_error="Unsupported preview state repaired by migration 0033.")
        )
        conn.execute(
            chapters.update()
            .where(chapters.c.generation_state.not_in(("pending", "processing", "ready", "error")))
            .values(generation_state="error")
        )

    if inspector.has_table("imported_audiobooks"):
        editions = _table(
            conn,
            "imported_audiobooks",
            {"alignment_method": sa.String(), "alignment_error": sa.Text()},
        )
        conn.execute(
            editions.update()
            .where(
                editions.c.alignment_method.is_not(None),
                editions.c.alignment_method.not_in(("estimated", "transcribed", "hybrid")),
            )
            .values(
                alignment_method=None,
                alignment_error="Unsupported alignment method cleared by migration 0033.",
            )
        )


def upgrade():
    conn = op.get_bind()
    _normalize_existing_values(conn)
    inspector = sa.inspect(conn)
    for table_name, constraints in CONSTRAINTS.items():
        if not inspector.has_table(table_name):
            continue
        existing = {constraint["name"] for constraint in inspector.get_check_constraints(table_name)}
        for constraint_name, (column_name, values) in constraints.items():
            if constraint_name in existing:
                continue
            allowed = ", ".join(f"'{value}'" for value in values)
            op.create_check_constraint(constraint_name, table_name, f"{column_name} IN ({allowed})")


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    for table_name, constraints in CONSTRAINTS.items():
        if not inspector.has_table(table_name):
            continue
        existing = {constraint["name"] for constraint in inspector.get_check_constraints(table_name)}
        for constraint_name in reversed(tuple(constraints)):
            if constraint_name in existing:
                op.drop_constraint(constraint_name, table_name, type_="check")
