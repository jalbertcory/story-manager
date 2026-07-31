"""add human-narrated audiobook editions and sentence timing

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-29 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

# Upgrade and downgrade normally run in separate processes, so persist object
# ownership in PostgreSQL's schema metadata instead of relying on module state.
_CREATED_TABLE_COMMENT = "story-manager:alembic:0024"


def _created_by_this_migration(conn, table_name: str) -> bool:
    inspector = sa.inspect(conn)
    if not inspector.has_table(table_name):
        return False
    try:
        return inspector.get_table_comment(table_name).get("text") == _CREATED_TABLE_COMMENT
    except NotImplementedError:
        return False


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table("books"):
        return

    if not inspector.has_table("imported_audiobooks"):
        op.create_table(
            "imported_audiobooks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("source_type", sa.String(), nullable=False, server_default="upload"),
            sa.Column("asin", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("alignment_method", sa.String(), nullable=True),
            sa.Column("original_filenames", sa.JSON(), nullable=True),
            sa.Column("duration_ms", sa.BigInteger(), nullable=True),
            sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("progress_detail", sa.String(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            comment=_CREATED_TABLE_COMMENT,
        )
        op.create_index("ix_imported_audiobooks_id", "imported_audiobooks", ["id"])
        op.create_index("ix_imported_audiobooks_book_id", "imported_audiobooks", ["book_id"])
        op.create_index("ix_imported_audiobooks_asin", "imported_audiobooks", ["asin"])
        op.create_index("ix_imported_audiobooks_status", "imported_audiobooks", ["status"])

    inspector = sa.inspect(conn)
    if not inspector.has_table("imported_audiobook_tracks"):
        op.create_table(
            "imported_audiobook_tracks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "imported_audiobook_id",
                sa.Integer(),
                sa.ForeignKey("imported_audiobooks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "matched_chapter_id",
                sa.Integer(),
                sa.ForeignKey("audiobook_chapters.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("sequence_order", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("audio_file_path", sa.String(), nullable=False),
            sa.Column("media_type", sa.String(), nullable=False),
            sa.Column("source_start_ms", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("source_end_ms", sa.BigInteger(), nullable=False),
            sa.Column("duration_ms", sa.BigInteger(), nullable=False),
            sa.UniqueConstraint(
                "imported_audiobook_id",
                "sequence_order",
                name="uq_imported_audiobook_track_order",
            ),
            comment=_CREATED_TABLE_COMMENT,
        )
        op.create_index("ix_imported_audiobook_tracks_id", "imported_audiobook_tracks", ["id"])
        op.create_index(
            "ix_imported_audiobook_tracks_imported_audiobook_id",
            "imported_audiobook_tracks",
            ["imported_audiobook_id"],
        )
        op.create_index(
            "ix_imported_audiobook_tracks_matched_chapter_id",
            "imported_audiobook_tracks",
            ["matched_chapter_id"],
        )

    inspector = sa.inspect(conn)
    if not inspector.has_table("imported_audiobook_cues"):
        op.create_table(
            "imported_audiobook_cues",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "track_id",
                sa.Integer(),
                sa.ForeignKey("imported_audiobook_tracks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "sentence_id",
                sa.Integer(),
                sa.ForeignKey("audiobook_sentences.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("sequence_order", sa.Integer(), nullable=False),
            sa.Column("clip_begin_ms", sa.BigInteger(), nullable=False),
            sa.Column("clip_end_ms", sa.BigInteger(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("method", sa.String(), nullable=False, server_default="estimated"),
            sa.UniqueConstraint("track_id", "sentence_id", name="uq_imported_audiobook_cue_sentence"),
            comment=_CREATED_TABLE_COMMENT,
        )
        op.create_index("ix_imported_audiobook_cues_id", "imported_audiobook_cues", ["id"])
        op.create_index("ix_imported_audiobook_cues_track_id", "imported_audiobook_cues", ["track_id"])
        op.create_index("ix_imported_audiobook_cues_sentence_id", "imported_audiobook_cues", ["sentence_id"])


def downgrade():
    conn = op.get_bind()
    if _created_by_this_migration(conn, "imported_audiobook_cues"):
        op.drop_table("imported_audiobook_cues")
    if _created_by_this_migration(conn, "imported_audiobook_tracks"):
        op.drop_table("imported_audiobook_tracks")
    if _created_by_this_migration(conn, "imported_audiobooks"):
        op.drop_table("imported_audiobooks")
