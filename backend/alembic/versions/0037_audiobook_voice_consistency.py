"""add audiobook voice-consistency controls and diagnostics

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-24 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def _column_names(conn, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(conn).get_columns(table_name)}


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("audiobook_settings"):
        columns = _column_names(conn, "audiobook_settings")
        for name, column_type, default in (
            ("tts_max_block_chars", sa.Integer(), "500"),
            ("tts_voice_similarity_threshold", sa.Float(), "0.45"),
            ("tts_quality_attempts", sa.Integer(), "3"),
        ):
            if name not in columns:
                op.add_column(
                    "audiobook_settings",
                    sa.Column(name, column_type, nullable=False, server_default=default),
                )

    for table_name in ("audiobook_series_characters", "audiobook_characters"):
        if inspector.has_table(table_name) and "tts_seed" not in _column_names(conn, table_name):
            op.add_column(table_name, sa.Column("tts_seed", sa.Integer(), nullable=True))

    if inspector.has_table("audiobook_sentences"):
        columns = _column_names(conn, "audiobook_sentences")
        for name, column_type in (
            ("generation_group_id", sa.String(length=64)),
            ("voice_similarity", sa.Float()),
            ("tts_attempts", sa.Integer()),
        ):
            if name not in columns:
                op.add_column("audiobook_sentences", sa.Column(name, column_type, nullable=True))
        indexes = {index["name"] for index in sa.inspect(conn).get_indexes("audiobook_sentences")}
        if "ix_audiobook_sentences_generation_group_id" not in indexes:
            op.create_index(
                "ix_audiobook_sentences_generation_group_id",
                "audiobook_sentences",
                ["generation_group_id"],
                unique=False,
            )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if inspector.has_table("audiobook_sentences"):
        columns = _column_names(conn, "audiobook_sentences")
        indexes = {index["name"] for index in inspector.get_indexes("audiobook_sentences")}
        if "ix_audiobook_sentences_generation_group_id" in indexes:
            op.drop_index("ix_audiobook_sentences_generation_group_id", table_name="audiobook_sentences")
        for name in ("tts_attempts", "voice_similarity", "generation_group_id"):
            if name in columns:
                op.drop_column("audiobook_sentences", name)
    for table_name in ("audiobook_characters", "audiobook_series_characters"):
        if inspector.has_table(table_name) and "tts_seed" in _column_names(conn, table_name):
            op.drop_column(table_name, "tts_seed")
    if inspector.has_table("audiobook_settings"):
        columns = _column_names(conn, "audiobook_settings")
        for name in ("tts_quality_attempts", "tts_voice_similarity_threshold", "tts_max_block_chars"):
            if name in columns:
                op.drop_column("audiobook_settings", name)
