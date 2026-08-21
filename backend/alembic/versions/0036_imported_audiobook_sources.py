"""track immutable imported audiobook sources and derived revisions

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-21 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def _column_names(conn, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(conn).get_columns(table_name)}


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("imported_audiobooks"):
        columns = _column_names(conn, "imported_audiobooks")
        additions = (
            ("source_manifest_file_path", sa.String()),
            ("source_manifest_sha256", sa.String(length=64)),
            ("source_size_bytes", sa.BigInteger()),
            ("derived_revision", sa.Integer(), "0"),
            ("derived_format_version", sa.Integer(), "0"),
        )
        for addition in additions:
            name, column_type, *default = addition
            if name in columns:
                continue
            op.add_column(
                "imported_audiobooks",
                sa.Column(
                    name,
                    column_type,
                    nullable=not default,
                    server_default=default[0] if default else None,
                ),
            )

    if inspector.has_table("imported_audiobook_tracks"):
        columns = _column_names(conn, "imported_audiobook_tracks")
        additions = (
            ("source_audio_file_path", sa.String()),
            ("source_clip_begin_ms", sa.BigInteger()),
            ("source_clip_end_ms", sa.BigInteger()),
        )
        for name, column_type in additions:
            if name not in columns:
                op.add_column("imported_audiobook_tracks", sa.Column(name, column_type, nullable=True))

        tracks = sa.table(
            "imported_audiobook_tracks",
            sa.column("audio_file_path", sa.String),
            sa.column("source_audio_file_path", sa.String),
            sa.column("source_start_ms", sa.BigInteger),
            sa.column("source_end_ms", sa.BigInteger),
            sa.column("source_clip_begin_ms", sa.BigInteger),
            sa.column("source_clip_end_ms", sa.BigInteger),
        )
        conn.execute(
            tracks.update()
            .where(tracks.c.source_audio_file_path.is_(None))
            .values(
                source_audio_file_path=tracks.c.audio_file_path,
                source_clip_begin_ms=tracks.c.source_start_ms,
                source_clip_end_ms=tracks.c.source_end_ms,
            )
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if inspector.has_table("imported_audiobook_tracks"):
        columns = _column_names(conn, "imported_audiobook_tracks")
        for name in ("source_clip_end_ms", "source_clip_begin_ms", "source_audio_file_path"):
            if name in columns:
                op.drop_column("imported_audiobook_tracks", name)
    if inspector.has_table("imported_audiobooks"):
        columns = _column_names(conn, "imported_audiobooks")
        for name in (
            "derived_format_version",
            "derived_revision",
            "source_size_bytes",
            "source_manifest_sha256",
            "source_manifest_file_path",
        ):
            if name in columns:
                op.drop_column("imported_audiobooks", name)
