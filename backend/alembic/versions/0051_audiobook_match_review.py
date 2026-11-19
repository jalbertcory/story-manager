"""store why imported audiobook chapter matches need review

Chapter-match safety blocks were stored as an import error, which made an
edition unplayable even though its audio had imported. The reason now lives in
``imported_audiobooks.match_review_reason`` on an otherwise ready edition: the
audio plays, and only synchronized text and alignment wait for review.

Blocked editions with tracks become ready and keep their reason. Ready editions
were checked live on every read and have no stored reason yet, so this queues
one ``revalidate_audiobook_matches`` job to record it. That check needs the
application's chapter-matching rules, so it runs in the worker rather than in
this migration.

Revision ID: 0051
Revises: 0050
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

TABLE = "imported_audiobooks"
COLUMN = "match_review_reason"
MATCH_REVIEW_PREFIX = "Chapter matching needs review."
_JOB_TYPE = "revalidate_audiobook_matches"
_DEDUPE_KEY = f"{_JOB_TYPE}:migration-0051"

_editions = sa.table(
    TABLE,
    sa.column("id", sa.Integer),
    sa.column("status", sa.String),
    sa.column("error", sa.Text),
    sa.column("alignment_method", sa.String),
    sa.column("progress_detail", sa.String),
    sa.column(COLUMN, sa.Text),
)
_tracks = sa.table(
    "imported_audiobook_tracks",
    sa.column("id", sa.Integer),
    sa.column("imported_audiobook_id", sa.Integer),
)
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


def _has_column(conn: sa.engine.Connection) -> bool:
    return any(column["name"] == COLUMN for column in sa.inspect(conn).get_columns(TABLE))


def _has_tracks() -> sa.ColumnElement[bool]:
    return sa.exists().where(_tracks.c.imported_audiobook_id == _editions.c.id)


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(TABLE):
        return
    if not _has_column(conn):
        op.add_column(TABLE, sa.Column(COLUMN, sa.Text(), nullable=True))
    if not inspector.has_table("imported_audiobook_tracks"):
        return

    # The audio imported; only the matches were blocked. Imports that failed
    # for any other reason, or left no tracks, stay failed.
    conn.execute(
        _editions.update()
        .where(
            _editions.c.status == "error",
            _editions.c.error.like(f"{MATCH_REVIEW_PREFIX}%"),
            _has_tracks(),
        )
        .values(
            status="ready",
            match_review_reason=_editions.c.error,
            error=None,
            alignment_method=sa.func.coalesce(_editions.c.alignment_method, "estimated"),
            progress_detail="Chapter matching needs review",
        )
    )

    if not inspector.has_table("processing_jobs"):
        return
    ready = conn.execute(sa.select(_editions.c.id).where(_editions.c.status == "ready").limit(1)).fetchone()
    active = conn.execute(
        sa.select(_jobs.c.job_type).where(
            _jobs.c.dedupe_key == _DEDUPE_KEY,
            _jobs.c.status.in_(("queued", "running")),
        )
    ).fetchone()
    if ready is not None and active is None:
        conn.execute(
            _jobs.insert().values(
                job_type=_JOB_TYPE,
                status="queued",
                resource_lane="maintenance",
                request_id="migration-0051",
                payload={},
                dedupe_key=_DEDUPE_KEY,
                max_attempts=3,
                progress_detail="Queued to check human audiobook chapter matches",
            )
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if inspector.has_table("processing_jobs"):
        # Older workers reject this job type, so drop any run that has not finished.
        conn.execute(
            _jobs.delete().where(
                _jobs.c.job_type == _JOB_TYPE,
                _jobs.c.status.in_(("queued", "running")),
            )
        )
    if not inspector.has_table(TABLE) or not _has_column(conn):
        return
    # Earlier releases recorded a match block as an import error.
    conn.execute(
        _editions.update()
        .where(_editions.c.status == "ready", _editions.c[COLUMN].is_not(None))
        .values(
            status="error",
            error=_editions.c[COLUMN],
            progress_detail="Chapter matching blocked; review required",
        )
    )
    op.drop_column(TABLE, COLUMN)
