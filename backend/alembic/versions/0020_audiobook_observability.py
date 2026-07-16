"""add audiobook LLM observability and batch controls

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-14 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("books", sa.Column("audiobook_summary", sa.Text(), nullable=True))
    op.add_column(
        "books",
        sa.Column("audiobook_progress_current", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "books",
        sa.Column("audiobook_progress_total", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("books", sa.Column("audiobook_progress_detail", sa.String(), nullable=True))
    op.add_column("books", sa.Column("audiobook_pipeline_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("books", sa.Column("audiobook_pipeline_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("books", sa.Column("audiobook_batch_limit", sa.Integer(), nullable=True))
    op.add_column(
        "books",
        sa.Column("audiobook_llm_requests", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column("audiobook_chapters", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "audiobook_chapters",
        sa.Column("summary_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("audiobook_characters", sa.Column("aliases", sa.JSON(), nullable=True))
    op.add_column("audiobook_characters", sa.Column("evidence", sa.JSON(), nullable=True))
    op.add_column("audiobook_sentences", sa.Column("speaker_confidence", sa.Float(), nullable=True))
    op.add_column("audiobook_sentences", sa.Column("speaker_reason", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("audiobook_sentences", "speaker_reason")
    op.drop_column("audiobook_sentences", "speaker_confidence")
    op.drop_column("audiobook_characters", "evidence")
    op.drop_column("audiobook_characters", "aliases")
    op.drop_column("audiobook_chapters", "summary_updated_at")
    op.drop_column("audiobook_chapters", "summary")
    op.drop_column("books", "audiobook_llm_requests")
    op.drop_column("books", "audiobook_batch_limit")
    op.drop_column("books", "audiobook_pipeline_updated_at")
    op.drop_column("books", "audiobook_pipeline_started_at")
    op.drop_column("books", "audiobook_progress_detail")
    op.drop_column("books", "audiobook_progress_total")
    op.drop_column("books", "audiobook_progress_current")
    op.drop_column("books", "audiobook_summary")
