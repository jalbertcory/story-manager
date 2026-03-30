"""add metadata sync fields to books

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-28 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("books"):
        columns = {column["name"] for column in inspector.get_columns("books")}
        if "genre_tags" not in columns:
            op.add_column("books", sa.Column("genre_tags", sa.JSON(), nullable=True))
        if "metadata_remote_ids" not in columns:
            op.add_column("books", sa.Column("metadata_remote_ids", sa.JSON(), nullable=True))
        if "metadata_sync_source" not in columns:
            op.add_column("books", sa.Column("metadata_sync_source", sa.String(), nullable=True))
        if "metadata_synced_at" not in columns:
            op.add_column("books", sa.Column("metadata_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("books"):
        columns = {column["name"] for column in inspector.get_columns("books")}
        if "metadata_synced_at" in columns:
            op.drop_column("books", "metadata_synced_at")
        if "metadata_sync_source" in columns:
            op.drop_column("books", "metadata_sync_source")
        if "metadata_remote_ids" in columns:
            op.drop_column("books", "metadata_remote_ids")
        if "genre_tags" in columns:
            op.drop_column("books", "genre_tags")
