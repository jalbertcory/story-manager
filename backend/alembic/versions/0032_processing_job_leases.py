"""add processing job resource lanes and leases

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-09 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

_COLUMN_COMMENT = "story-manager:alembic:0032"

_LANES = {
    "clean_book": "cpu",
    "clean_all": "cpu",
    "refresh_book": "maintenance",
    "refresh_all": "maintenance",
    "import_web_book": "maintenance",
    "retry_cover": "maintenance",
    "metadata_sync": "llm",
    "audiobook_pipeline": "llm",
    "generate_sentence_audio": "tts",
    "generate_chapter_preview": "tts",
    "import_audiobook": "cpu",
    "rematch_imported_audiobook": "cpu",
    "align_imported_audiobook": "transcription",
}


def _columns(conn) -> set[str]:
    inspector = sa.inspect(conn)
    if not inspector.has_table("processing_jobs"):
        return set()
    return {column["name"] for column in inspector.get_columns("processing_jobs")}


def _indexes(conn) -> set[str]:
    return {index["name"] for index in sa.inspect(conn).get_indexes("processing_jobs")}


def upgrade():
    conn = op.get_bind()
    if not sa.inspect(conn).has_table("processing_jobs"):
        return

    columns = _columns(conn)
    additions = (
        (
            "resource_lane",
            sa.Column("resource_lane", sa.String(), nullable=False, server_default="maintenance", comment=_COLUMN_COMMENT),
        ),
        ("max_attempts", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3", comment=_COLUMN_COMMENT)),
        (
            "available_at",
            sa.Column(
                "available_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
                comment=_COLUMN_COMMENT,
            ),
        ),
        ("lease_owner", sa.Column("lease_owner", sa.String(), nullable=True, comment=_COLUMN_COMMENT)),
        (
            "lease_expires_at",
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True, comment=_COLUMN_COMMENT),
        ),
        ("heartbeat_at", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True, comment=_COLUMN_COMMENT)),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("processing_jobs", column)

    jobs = sa.table(
        "processing_jobs",
        sa.column("job_type", sa.String),
        sa.column("status", sa.String),
        sa.column("resource_lane", sa.String),
        sa.column("lease_owner", sa.String),
        sa.column("lease_expires_at", sa.DateTime(timezone=True)),
    )
    for job_type, lane in _LANES.items():
        conn.execute(jobs.update().where(jobs.c.job_type == job_type).values(resource_lane=lane))

    conn.execute(
        jobs.update()
        .where(jobs.c.status == "running")
        .values(lease_owner="pre-0032-worker", lease_expires_at=sa.func.current_timestamp())
    )

    if sa.inspect(conn).has_table("books"):
        books = sa.table(
            "books",
            sa.column("id", sa.Integer),
            sa.column("source_url", sa.String),
            sa.column("download_status", sa.String),
        )
        pending_books = conn.execute(
            sa.select(books.c.id, books.c.source_url).where(
                books.c.source_url.is_not(None),
                books.c.download_status == "pending",
            )
        ).fetchall()
        processing_jobs = sa.table(
            "processing_jobs",
            sa.column("job_type", sa.String),
            sa.column("status", sa.String),
            sa.column("resource_lane", sa.String),
            sa.column("book_id", sa.Integer),
            sa.column("target_type", sa.String),
            sa.column("target_id", sa.Integer),
            sa.column("payload", sa.JSON),
            sa.column("dedupe_key", sa.String),
            sa.column("progress_detail", sa.String),
        )
        for book_id, source_url in pending_books:
            active = conn.execute(
                sa.select(processing_jobs.c.target_id).where(
                    processing_jobs.c.dedupe_key == f"import_web_book:book:{book_id}",
                    processing_jobs.c.status.in_(("queued", "running")),
                )
            ).fetchone()
            if active is None:
                conn.execute(
                    processing_jobs.insert().values(
                        job_type="import_web_book",
                        status="queued",
                        resource_lane="maintenance",
                        book_id=book_id,
                        target_type="book",
                        target_id=book_id,
                        payload={"source_url": source_url, "legacy_resume": True},
                        dedupe_key=f"import_web_book:book:{book_id}",
                        progress_detail="Queued after leased-worker migration",
                    )
                )

    # Keep the newest active owner for each idempotency key before enforcing
    # the invariant at the database boundary.
    conn.execute(
        sa.text(
            "UPDATE processing_jobs SET status = 'canceled', "
            "progress_detail = 'Superseded during worker consolidation', completed_at = CURRENT_TIMESTAMP "
            "WHERE id IN ("
            "SELECT id FROM ("
            "SELECT id, row_number() OVER (PARTITION BY dedupe_key ORDER BY id DESC) AS position "
            "FROM processing_jobs WHERE dedupe_key IS NOT NULL AND status IN ('queued', 'running')"
            ") duplicates WHERE position > 1"
            ")"
        )
    )

    indexes = _indexes(conn)
    if "ix_processing_jobs_resource_lane" not in indexes:
        op.create_index("ix_processing_jobs_resource_lane", "processing_jobs", ["resource_lane"])
    if "ix_processing_jobs_available_at" not in indexes:
        op.create_index("ix_processing_jobs_available_at", "processing_jobs", ["available_at"])
    if "ix_processing_jobs_lease_expires_at" not in indexes:
        op.create_index("ix_processing_jobs_lease_expires_at", "processing_jobs", ["lease_expires_at"])
    if "ix_processing_jobs_claim" not in indexes:
        op.create_index(
            "ix_processing_jobs_claim",
            "processing_jobs",
            ["status", "resource_lane", "available_at", "lease_expires_at", "created_at"],
        )
    if "uq_processing_jobs_active_dedupe" not in indexes:
        op.create_index(
            "uq_processing_jobs_active_dedupe",
            "processing_jobs",
            ["dedupe_key"],
            unique=True,
            postgresql_where=sa.text("dedupe_key IS NOT NULL AND status IN ('queued', 'running')"),
            sqlite_where=sa.text("dedupe_key IS NOT NULL AND status IN ('queued', 'running')"),
        )


def downgrade():
    conn = op.get_bind()
    if not sa.inspect(conn).has_table("processing_jobs"):
        return
    jobs = sa.table(
        "processing_jobs",
        sa.column("id", sa.Integer),
        sa.column("job_type", sa.String),
        sa.column("payload", sa.JSON),
        sa.column("progress_detail", sa.String),
    )
    seeded_ids = [
        row.id
        for row in conn.execute(
            sa.select(jobs.c.id, jobs.c.payload).where(
                jobs.c.job_type == "import_web_book",
                jobs.c.progress_detail == "Queued after leased-worker migration",
            )
        )
        if (row.payload or {}).get("legacy_resume") is True
    ]
    if seeded_ids:
        conn.execute(jobs.delete().where(jobs.c.id.in_(seeded_ids)))

    indexes = _indexes(conn)
    for name in (
        "uq_processing_jobs_active_dedupe",
        "ix_processing_jobs_claim",
        "ix_processing_jobs_lease_expires_at",
        "ix_processing_jobs_available_at",
        "ix_processing_jobs_resource_lane",
    ):
        if name in indexes:
            op.drop_index(name, table_name="processing_jobs")

    columns = {column["name"]: column for column in sa.inspect(conn).get_columns("processing_jobs")}
    for name in ("heartbeat_at", "lease_expires_at", "lease_owner", "available_at", "max_attempts", "resource_lane"):
        if columns.get(name, {}).get("comment") == _COLUMN_COMMENT:
            op.drop_column("processing_jobs", name)
