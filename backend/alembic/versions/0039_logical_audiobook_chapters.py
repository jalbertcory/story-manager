"""group physical EPUB sections into logical audiobook chapters

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-27 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def _column_names(conn, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(conn).get_columns(table_name)}


def _index_names(conn, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(conn).get_indexes(table_name)}


def upgrade():
    conn = op.get_bind()
    if not sa.inspect(conn).has_table("audiobook_chapters"):
        return

    columns = _column_names(conn, "audiobook_chapters")
    if "logical_chapter_key" not in columns:
        op.add_column("audiobook_chapters", sa.Column("logical_chapter_key", sa.String(), nullable=True))
    if "logical_part_order" not in columns:
        op.add_column("audiobook_chapters", sa.Column("logical_part_order", sa.Integer(), nullable=True))

    index_name = "ix_audiobook_chapters_book_logical_key"
    if index_name not in _index_names(conn, "audiobook_chapters"):
        op.create_index(
            index_name,
            "audiobook_chapters",
            ["book_id", "logical_chapter_key"],
            unique=False,
        )


def downgrade():
    conn = op.get_bind()
    if not sa.inspect(conn).has_table("audiobook_chapters"):
        return

    index_name = "ix_audiobook_chapters_book_logical_key"
    if index_name in _index_names(conn, "audiobook_chapters"):
        op.drop_index(index_name, table_name="audiobook_chapters")

    columns = _column_names(conn, "audiobook_chapters")
    if "logical_part_order" in columns:
        op.drop_column("audiobook_chapters", "logical_part_order")
    if "logical_chapter_key" in columns:
        op.drop_column("audiobook_chapters", "logical_chapter_key")
