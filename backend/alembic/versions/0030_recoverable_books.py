"""add recycle bin and restorable book revisions

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-09 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

_TABLE = "book_revisions"
_TABLE_COMMENT = "story-manager:alembic:0030"
_COLUMN_COMMENT = "story-manager:alembic:0030"


def _index_names(conn, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(conn).get_indexes(table_name)}


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table("books"):
        return

    columns = {column["name"] for column in inspector.get_columns("books")}
    if "deleted_at" not in columns:
        op.add_column(
            "books",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, comment=_COLUMN_COMMENT),
        )
    if "purge_after" not in columns:
        op.add_column(
            "books",
            sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True, comment=_COLUMN_COMMENT),
        )

    book_indexes = _index_names(conn, "books")
    if "ix_books_deleted_at" not in book_indexes:
        op.create_index("ix_books_deleted_at", "books", ["deleted_at"], unique=False)
    if "ix_books_purge_after" not in book_indexes:
        op.create_index("ix_books_purge_after", "books", ["purge_after"], unique=False)

    if not sa.inspect(conn).has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("summary", sa.String(), nullable=False),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            comment=_TABLE_COMMENT,
        )

    revision_indexes = _index_names(conn, _TABLE)
    if "ix_book_revisions_book_id" not in revision_indexes:
        op.create_index("ix_book_revisions_book_id", _TABLE, ["book_id"], unique=False)
    if "ix_book_revisions_created_at" not in revision_indexes:
        op.create_index("ix_book_revisions_created_at", _TABLE, ["created_at"], unique=False)
    if "ix_book_revisions_book_created" not in revision_indexes:
        op.create_index("ix_book_revisions_book_created", _TABLE, ["book_id", "created_at"], unique=False)


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table(_TABLE):
        try:
            table_comment = inspector.get_table_comment(_TABLE).get("text")
        except NotImplementedError:
            table_comment = None
        if table_comment == _TABLE_COMMENT:
            op.drop_table(_TABLE)

    if not sa.inspect(conn).has_table("books"):
        return

    indexes = _index_names(conn, "books")
    if "ix_books_purge_after" in indexes:
        op.drop_index("ix_books_purge_after", table_name="books")
    if "ix_books_deleted_at" in indexes:
        op.drop_index("ix_books_deleted_at", table_name="books")

    columns = {column["name"]: column for column in sa.inspect(conn).get_columns("books")}
    if columns.get("purge_after", {}).get("comment") == _COLUMN_COMMENT:
        op.drop_column("books", "purge_after")
    if columns.get("deleted_at", {}).get("comment") == _COLUMN_COMMENT:
        op.drop_column("books", "deleted_at")
