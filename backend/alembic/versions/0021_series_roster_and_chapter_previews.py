"""add shared series rosters and manual chapter preview state

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-15 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audiobook_series_characters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("series_name", sa.String(), nullable=False),
        sa.Column("canonical_name", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("voice_design_prompt", sa.String(), nullable=True),
        sa.Column("is_narrator", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("series_name", "canonical_name", name="uq_audiobook_series_character"),
    )
    op.create_index(
        "ix_audiobook_series_characters_series_name",
        "audiobook_series_characters",
        ["series_name"],
    )
    op.add_column("audiobook_characters", sa.Column("series_character_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_audiobook_characters_series_character_id",
        "audiobook_characters",
        ["series_character_id"],
    )
    op.create_foreign_key(
        "fk_audiobook_characters_series_character_id",
        "audiobook_characters",
        "audiobook_series_characters",
        ["series_character_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("audiobook_chapters", sa.Column("preview_status", sa.String(), nullable=True))
    op.add_column("audiobook_chapters", sa.Column("preview_error", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("audiobook_chapters", "preview_error")
    op.drop_column("audiobook_chapters", "preview_status")
    op.drop_constraint(
        "fk_audiobook_characters_series_character_id",
        "audiobook_characters",
        type_="foreignkey",
    )
    op.drop_index("ix_audiobook_characters_series_character_id", table_name="audiobook_characters")
    op.drop_column("audiobook_characters", "series_character_id")
    op.drop_index(
        "ix_audiobook_series_characters_series_name",
        table_name="audiobook_series_characters",
    )
    op.drop_table("audiobook_series_characters")
