"""add durable processing jobs and imported-audio content tracking

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-31 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

_CREATED_TABLE_COMMENT = "story-manager:alembic:0026:processing-jobs"
_CREATED_COLUMN_COMMENT = "story-manager:alembic:0026"


def _columns(conn, table_name: str) -> dict[str, dict]:
    inspector = sa.inspect(conn)
    if not inspector.has_table(table_name):
        return {}
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _seed_legacy_jobs(conn) -> None:
    """Preserve work that was queued through the pre-0026 status columns."""
    jobs = sa.table(
        "processing_jobs",
        sa.column("job_type", sa.String),
        sa.column("status", sa.String),
        sa.column("book_id", sa.Integer),
        sa.column("target_type", sa.String),
        sa.column("target_id", sa.Integer),
        sa.column("target_content_version", sa.Integer),
        sa.column("payload", sa.JSON),
        sa.column("dedupe_key", sa.String),
        sa.column("progress_detail", sa.String),
    )

    if sa.inspect(conn).has_table("books"):
        books = sa.table(
            "books",
            sa.column("id", sa.Integer),
            sa.column("content_version", sa.Integer),
            sa.column("refresh_status", sa.String),
            sa.column("audiobook_pipeline_status", sa.String),
        )
        rows = conn.execute(
            sa.select(
                books.c.id,
                books.c.content_version,
                books.c.refresh_status,
                books.c.audiobook_pipeline_status,
            )
        ).fetchall()
        active_audio = {"ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"}
        for row in rows:
            if row.refresh_status in {"queued", "processing"}:
                conn.execute(
                    jobs.insert().values(
                        job_type="refresh_book",
                        status="queued",
                        book_id=row.id,
                        target_type="book",
                        target_id=row.id,
                        target_content_version=row.content_version,
                        payload={"legacy_resume": True},
                        dedupe_key=f"refresh_book:book:{row.id}",
                        progress_detail="Queued after processing-jobs migration",
                    )
                )
            if row.audiobook_pipeline_status in active_audio:
                conn.execute(
                    jobs.insert().values(
                        job_type="audiobook_pipeline",
                        status="queued",
                        book_id=row.id,
                        target_type="book",
                        target_id=row.id,
                        target_content_version=row.content_version,
                        payload={"mode": "resume", "legacy_resume": True},
                        dedupe_key=f"audiobook_pipeline:book:{row.id}:v{row.content_version or 1}",
                        progress_detail="Queued after processing-jobs migration",
                    )
                )

    if sa.inspect(conn).has_table("imported_audiobooks"):
        editions = sa.table(
            "imported_audiobooks",
            sa.column("id", sa.Integer),
            sa.column("book_id", sa.Integer),
            sa.column("status", sa.String),
        )
        for row in conn.execute(
            sa.select(editions.c.id, editions.c.book_id, editions.c.status).where(
                editions.c.status.in_(("queued", "importing", "aligning"))
            )
        ).fetchall():
            job_type = "align_imported_audiobook" if row.status == "aligning" else "import_audiobook"
            conn.execute(
                jobs.insert().values(
                    job_type=job_type,
                    status="queued",
                    book_id=row.book_id,
                    target_type="imported_audiobook",
                    target_id=row.id,
                    payload={"legacy_resume": True},
                    dedupe_key=f"{job_type}:imported_audiobook:{row.id}",
                    progress_detail="Queued after processing-jobs migration",
                )
            )

    if sa.inspect(conn).has_table("audiobook_chapters"):
        chapters = sa.table(
            "audiobook_chapters",
            sa.column("id", sa.Integer),
            sa.column("book_id", sa.Integer),
            sa.column("preview_status", sa.String),
        )
        for row in conn.execute(
            sa.select(chapters.c.id, chapters.c.book_id).where(chapters.c.preview_status.in_(("queued", "generating")))
        ).fetchall():
            conn.execute(
                jobs.insert().values(
                    job_type="generate_chapter_preview",
                    status="queued",
                    book_id=row.book_id,
                    target_type="audiobook_chapter",
                    target_id=row.id,
                    payload={"legacy_resume": True},
                    dedupe_key=f"generate_chapter_preview:audiobook_chapter:{row.id}",
                    progress_detail="Queued after processing-jobs migration",
                )
            )

        if sa.inspect(conn).has_table("audiobook_sentences"):
            sentences = sa.table(
                "audiobook_sentences",
                sa.column("id", sa.Integer),
                sa.column("chapter_id", sa.Integer),
                sa.column("status", sa.String),
            )
            rows = conn.execute(
                sa.select(sentences.c.id, chapters.c.book_id)
                .select_from(sentences.join(chapters, sentences.c.chapter_id == chapters.c.id))
                .where(sentences.c.status.in_(("audio_queued", "audio_generating")))
            ).fetchall()
            for row in rows:
                conn.execute(
                    jobs.insert().values(
                        job_type="generate_sentence_audio",
                        status="queued",
                        book_id=row.book_id,
                        target_type="audiobook_sentence",
                        target_id=row.id,
                        payload={"legacy_resume": True},
                        dedupe_key=f"generate_sentence_audio:audiobook_sentence:{row.id}",
                        progress_detail="Queued after processing-jobs migration",
                    )
                )

    if sa.inspect(conn).has_table("metadata_sync_jobs"):
        metadata_jobs = sa.table(
            "metadata_sync_jobs",
            sa.column("id", sa.Integer),
            sa.column("status", sa.String),
        )
        for row in conn.execute(
            sa.select(metadata_jobs.c.id).where(metadata_jobs.c.status.in_(("queued", "running")))
        ).fetchall():
            conn.execute(
                jobs.insert().values(
                    job_type="metadata_sync",
                    status="queued",
                    target_type="metadata_sync_job",
                    target_id=row.id,
                    payload={"metadata_job_id": row.id, "legacy_resume": True},
                    dedupe_key=f"metadata_sync:metadata_sync_job:{row.id}",
                    progress_detail="Queued after processing-jobs migration",
                )
            )


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if not inspector.has_table("processing_jobs"):
        op.create_table(
            "processing_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=True),
            sa.Column("target_type", sa.String(), nullable=True),
            sa.Column("target_id", sa.Integer(), nullable=True),
            sa.Column("target_content_version", sa.Integer(), nullable=True),
            sa.Column("parent_job_id", sa.Integer(), sa.ForeignKey("processing_jobs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("dedupe_key", sa.String(), nullable=True),
            sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("progress_detail", sa.String(), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            comment=_CREATED_TABLE_COMMENT,
        )
        op.create_index("ix_processing_jobs_job_type", "processing_jobs", ["job_type"])
        op.create_index("ix_processing_jobs_status", "processing_jobs", ["status"])
        op.create_index("ix_processing_jobs_book_id", "processing_jobs", ["book_id"])
        op.create_index("ix_processing_jobs_dedupe_key", "processing_jobs", ["dedupe_key"])
        op.create_index("ix_processing_jobs_created_at", "processing_jobs", ["created_at"])
        _seed_legacy_jobs(conn)

    edition_columns = _columns(conn, "imported_audiobooks")
    if edition_columns and "matched_content_version" not in edition_columns:
        op.add_column(
            "imported_audiobooks",
            sa.Column("matched_content_version", sa.Integer(), nullable=True, comment=_CREATED_COLUMN_COMMENT),
        )
        imported = sa.table(
            "imported_audiobooks",
            sa.column("book_id", sa.Integer),
            sa.column("matched_content_version", sa.Integer),
        )
        books = sa.table("books", sa.column("id", sa.Integer), sa.column("content_version", sa.Integer))
        rows = conn.execute(
            sa.select(imported.c.book_id, books.c.content_version)
            .select_from(imported.join(books, imported.c.book_id == books.c.id))
            .distinct()
        ).fetchall()
        for row in rows:
            conn.execute(
                imported.update()
                .where(imported.c.book_id == row.book_id)
                .values(matched_content_version=row.content_version or 1)
            )


def downgrade():
    conn = op.get_bind()

    edition_columns = _columns(conn, "imported_audiobooks")
    if edition_columns.get("matched_content_version", {}).get("comment") == _CREATED_COLUMN_COMMENT:
        op.drop_column("imported_audiobooks", "matched_content_version")

    inspector = sa.inspect(conn)
    if inspector.has_table("processing_jobs"):
        try:
            created_here = inspector.get_table_comment("processing_jobs").get("text") == _CREATED_TABLE_COMMENT
        except NotImplementedError:
            created_here = False
        if created_here:
            op.drop_table("processing_jobs")
