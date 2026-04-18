"""add series metadata

Revision ID: 0012
Revises: 0011
Create Date: 2026-03-31 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if not inspector.has_table("series_metadata"):
        op.create_table(
            "series_metadata",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("series_name", sa.String(), nullable=False),
            sa.Column("user_genre_tags", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("series_name"),
        )
        op.create_index("ix_series_metadata_id", "series_metadata", ["id"])
        op.create_index("ix_series_metadata_series_name", "series_metadata", ["series_name"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("series_metadata"):
        op.drop_index("ix_series_metadata_series_name", table_name="series_metadata")
        op.drop_index("ix_series_metadata_id", table_name="series_metadata")
        op.drop_table("series_metadata")
