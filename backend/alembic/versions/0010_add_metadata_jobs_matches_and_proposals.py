"""add metadata jobs matches and proposals

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if not inspector.has_table("metadata_sync_jobs"):
        op.create_table(
            "metadata_sync_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("trigger", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("total_books", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("processed_books", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matched_books", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("proposed_books", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("applied_books", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("scope", sa.JSON(), nullable=True),
            sa.Column("error", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not inspector.has_table("book_metadata_matches"):
        op.create_table(
            "book_metadata_matches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("source", sa.String(), nullable=True),
            sa.Column("match_confidence", sa.Numeric(5, 4), nullable=True),
            sa.Column("remote_title", sa.String(), nullable=True),
            sa.Column("remote_author", sa.String(), nullable=True),
            sa.Column("remote_url", sa.String(), nullable=True),
            sa.Column("remote_ids", sa.JSON(), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("book_id"),
        )
        op.create_index("ix_book_metadata_matches_book_id", "book_metadata_matches", ["book_id"])

    if not inspector.has_table("metadata_proposals"):
        op.create_table(
            "metadata_proposals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
            sa.Column("match_id", sa.Integer(), sa.ForeignKey("book_metadata_matches.id"), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="open"),
            sa.Column("proposed_genre_tags", sa.JSON(), nullable=True),
            sa.Column("possible_missing_series_books", sa.JSON(), nullable=True),
            sa.Column("note", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("book_id"),
        )
        op.create_index("ix_metadata_proposals_book_id", "metadata_proposals", ["book_id"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("metadata_proposals"):
        op.drop_index("ix_metadata_proposals_book_id", table_name="metadata_proposals")
        op.drop_table("metadata_proposals")

    if inspector.has_table("book_metadata_matches"):
        op.drop_index("ix_book_metadata_matches_book_id", table_name="book_metadata_matches")
        op.drop_table("book_metadata_matches")

    if inspector.has_table("metadata_sync_jobs"):
        op.drop_table("metadata_sync_jobs")
