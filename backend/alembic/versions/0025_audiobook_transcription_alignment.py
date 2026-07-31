"""add audiobook transcription and alignment configuration

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-30 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

# A schema comment lets downgrade distinguish columns added here from columns
# that were already present on a populated, historically create_all-managed DB.
_CREATED_COLUMN_COMMENT = "story-manager:alembic:0025"


def _columns(conn, table_name: str) -> dict[str, dict]:
    inspector = sa.inspect(conn)
    if not inspector.has_table(table_name):
        return {}
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def upgrade():
    conn = op.get_bind()

    settings_columns = _columns(conn, "audiobook_settings")
    for name, column_type in (
        ("transcription_provider", sa.String()),
        ("transcription_api_key", sa.String()),
        ("transcription_base_url", sa.String()),
        ("transcription_model", sa.String()),
        ("transcription_language", sa.String()),
    ):
        if settings_columns and name not in settings_columns:
            op.add_column(
                "audiobook_settings",
                sa.Column(name, column_type, nullable=True, comment=_CREATED_COLUMN_COMMENT),
            )

    edition_columns = _columns(conn, "imported_audiobooks")
    if edition_columns and "alignment_error" not in edition_columns:
        op.add_column(
            "imported_audiobooks",
            sa.Column("alignment_error", sa.Text(), nullable=True, comment=_CREATED_COLUMN_COMMENT),
        )

    track_columns = _columns(conn, "imported_audiobook_tracks")
    if track_columns and "transcript_file_path" not in track_columns:
        op.add_column(
            "imported_audiobook_tracks",
            sa.Column("transcript_file_path", sa.String(), nullable=True, comment=_CREATED_COLUMN_COMMENT),
        )
    if track_columns and "alignment_score" not in track_columns:
        op.add_column(
            "imported_audiobook_tracks",
            sa.Column("alignment_score", sa.Float(), nullable=True, comment=_CREATED_COLUMN_COMMENT),
        )


def downgrade():
    conn = op.get_bind()

    track_columns = _columns(conn, "imported_audiobook_tracks")
    if track_columns.get("alignment_score", {}).get("comment") == _CREATED_COLUMN_COMMENT:
        op.drop_column("imported_audiobook_tracks", "alignment_score")
    if track_columns.get("transcript_file_path", {}).get("comment") == _CREATED_COLUMN_COMMENT:
        op.drop_column("imported_audiobook_tracks", "transcript_file_path")

    edition_columns = _columns(conn, "imported_audiobooks")
    if edition_columns.get("alignment_error", {}).get("comment") == _CREATED_COLUMN_COMMENT:
        op.drop_column("imported_audiobooks", "alignment_error")

    settings_columns = _columns(conn, "audiobook_settings")
    for name in (
        "transcription_language",
        "transcription_model",
        "transcription_base_url",
        "transcription_api_key",
        "transcription_provider",
    ):
        if settings_columns.get(name, {}).get("comment") == _CREATED_COLUMN_COMMENT:
            op.drop_column("audiobook_settings", name)
