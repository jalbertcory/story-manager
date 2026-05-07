"""audiobook pipeline tables and book pipeline status column

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-07 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audiobook_settings",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("llm_provider", sa.String, nullable=True),
        sa.Column("llm_api_key", sa.String, nullable=True),
        sa.Column("llm_base_url", sa.String, nullable=True),
        sa.Column("llm_model", sa.String, nullable=True),
        sa.Column("omnivoice_endpoint", sa.String, nullable=True),
        sa.Column("roster_prompt_template", sa.Text, nullable=True),
        sa.Column("diarization_prompt_template", sa.Text, nullable=True),
    )

    op.create_table(
        "audiobook_chapters",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("book_id", sa.Integer, sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("chapter_number", sa.Integer, nullable=False),
        sa.Column("smil_file_path", sa.String, nullable=True),
        sa.Column("audio_file_path", sa.String, nullable=True),
        sa.Column("needs_reassembly", sa.Boolean, nullable=False, server_default="false"),
    )

    op.create_table(
        "audiobook_characters",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("book_id", sa.Integer, sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("voice_design_prompt", sa.String, nullable=True),
        sa.Column("is_narrator", sa.Boolean, nullable=False, server_default="false"),
    )

    op.create_table(
        "audiobook_sentences",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "chapter_id",
            sa.Integer,
            sa.ForeignKey("audiobook_chapters.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "character_id",
            sa.Integer,
            sa.ForeignKey("audiobook_characters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("html_element_id", sa.String, nullable=False),
        sa.Column("sequence_order", sa.Integer, nullable=False),
        sa.Column("original_text", sa.Text, nullable=False),
        sa.Column("tagged_text", sa.Text, nullable=True),
        sa.Column("audio_file_path", sa.String, nullable=True),
        sa.Column("audio_duration_ms", sa.Integer, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="pending_diarization"),
    )
    op.create_index("ix_audiobook_sentences_status", "audiobook_sentences", ["status"])

    op.add_column("books", sa.Column("audiobook_pipeline_status", sa.String, nullable=True))


def downgrade():
    op.drop_column("books", "audiobook_pipeline_status")
    op.drop_index("ix_audiobook_sentences_status", table_name="audiobook_sentences")
    op.drop_table("audiobook_sentences")
    op.drop_table("audiobook_characters")
    op.drop_table("audiobook_chapters")
    op.drop_table("audiobook_settings")
