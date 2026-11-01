"""queue a one-time backfill of reader audiobook sizes and hashes

Publications from before the reader stored file sizes and SHA-256 hashes left
those columns null, so the reader routes hash files on every request for them.
This queues one ``backfill_reader_checksums`` job when any such row exists; the
worker computes the values off the event loop. Hashing needs the library files,
so it runs in the worker rather than in this migration.

Revision ID: 0046
Revises: 0045
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None

_JOB_TYPE = "backfill_reader_checksums"
_DEDUPE_KEY = f"{_JOB_TYPE}:migration-0046"

_jobs = sa.table(
    "processing_jobs",
    sa.column("job_type", sa.String),
    sa.column("status", sa.String),
    sa.column("resource_lane", sa.String),
    sa.column("request_id", sa.String),
    sa.column("payload", sa.JSON),
    sa.column("dedupe_key", sa.String),
    sa.column("max_attempts", sa.Integer),
    sa.column("progress_detail", sa.String),
)


def _missing_checksums(conn: sa.engine.Connection) -> bool:
    inspector = sa.inspect(conn)
    if inspector.has_table("audiobook_chapters"):
        chapters = sa.table(
            "audiobook_chapters",
            sa.column("id", sa.Integer),
            sa.column("generation_state", sa.String),
            sa.column("audio_size_bytes", sa.Integer),
            sa.column("audio_sha256", sa.String),
            sa.column("smil_size_bytes", sa.Integer),
            sa.column("smil_sha256", sa.String),
        )
        missing = conn.execute(
            sa.select(chapters.c.id)
            .where(
                chapters.c.generation_state == "ready",
                sa.or_(
                    chapters.c.audio_size_bytes.is_(None),
                    chapters.c.audio_sha256.is_(None),
                    chapters.c.smil_size_bytes.is_(None),
                    chapters.c.smil_sha256.is_(None),
                ),
            )
            .limit(1)
        ).fetchone()
        if missing is not None:
            return True
    if inspector.has_table("books"):
        books = sa.table(
            "books",
            sa.column("id", sa.Integer),
            sa.column("audiobook_text_file_path", sa.String),
            sa.column("audiobook_text_size_bytes", sa.Integer),
            sa.column("audiobook_text_sha256", sa.String),
        )
        missing = conn.execute(
            sa.select(books.c.id)
            .where(
                books.c.audiobook_text_file_path.is_not(None),
                sa.or_(books.c.audiobook_text_size_bytes.is_(None), books.c.audiobook_text_sha256.is_(None)),
            )
            .limit(1)
        ).fetchone()
        if missing is not None:
            return True
    return False


def upgrade():
    conn = op.get_bind()
    if not sa.inspect(conn).has_table("processing_jobs") or not _missing_checksums(conn):
        return
    active = conn.execute(
        sa.select(_jobs.c.job_type).where(
            _jobs.c.dedupe_key == _DEDUPE_KEY,
            _jobs.c.status.in_(("queued", "running")),
        )
    ).fetchone()
    if active is None:
        conn.execute(
            _jobs.insert().values(
                job_type=_JOB_TYPE,
                status="queued",
                resource_lane="maintenance",
                request_id="migration-0046",
                payload={},
                dedupe_key=_DEDUPE_KEY,
                max_attempts=3,
                progress_detail="Queued to record reader audiobook checksums",
            )
        )


def downgrade():
    conn = op.get_bind()
    if not sa.inspect(conn).has_table("processing_jobs"):
        return
    # Older workers reject this job type, so drop any run that has not finished.
    conn.execute(
        _jobs.delete().where(
            _jobs.c.job_type == _JOB_TYPE,
            _jobs.c.status.in_(("queued", "running")),
        )
    )
