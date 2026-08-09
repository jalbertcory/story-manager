"""add catalog search text and pagination indexes

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-09 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

_COLUMN_COMMENT = "story-manager:alembic:0031"


def _index_names(conn) -> set[str]:
    return {index["name"] for index in sa.inspect(conn).get_indexes("books")}


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table("books"):
        return

    columns = {column["name"] for column in inspector.get_columns("books")}
    if "catalog_search_text" not in columns:
        op.add_column(
            "books",
            sa.Column("catalog_search_text", sa.Text(), nullable=True, comment=_COLUMN_COMMENT),
        )

    books = sa.table(
        "books",
        sa.column("id", sa.Integer),
        sa.column("title", sa.String),
        sa.column("author", sa.String),
        sa.column("series", sa.String),
        sa.column("genre_tags", sa.JSON),
        sa.column("user_genre_tags", sa.JSON),
        sa.column("catalog_search_text", sa.Text),
    )
    rows = conn.execute(
        sa.select(
            books.c.id,
            books.c.title,
            books.c.author,
            books.c.series,
            books.c.genre_tags,
            books.c.user_genre_tags,
        )
    )
    for row in rows:
        values = [row.title, row.author, row.series]
        tags = [*(row.genre_tags or []), *(row.user_genre_tags or [])]
        parts = [str(value).strip().casefold() for value in values if value and str(value).strip()]
        parts.extend(f"tag:{str(tag).strip().casefold()}" for tag in tags if tag and str(tag).strip())
        search_text = "\n".join(parts) + "\n"
        conn.execute(books.update().where(books.c.id == row.id).values(catalog_search_text=search_text))

    indexes = _index_names(conn)
    if "ix_books_catalog_series_page" not in indexes:
        op.create_index(
            "ix_books_catalog_series_page",
            "books",
            ["deleted_at", "series", "id"],
            unique=False,
        )

    if conn.dialect.name == "postgresql":
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_books_catalog_title_seek "
                "ON books (lower(coalesce(title, '')), id) WHERE deleted_at IS NULL"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_books_catalog_author_seek "
                "ON books (lower(coalesce(author, '')), lower(coalesce(title, '')), id) "
                "WHERE deleted_at IS NULL"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_books_catalog_word_count_seek "
                "ON books (coalesce(current_word_count, -1), lower(coalesce(title, '')), id) "
                "WHERE deleted_at IS NULL"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_books_catalog_updated_seek "
                "ON books (coalesce(updated_at, created_at), lower(coalesce(title, '')), id) "
                "WHERE deleted_at IS NULL"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_books_catalog_search_trgm "
                "ON books USING gin (catalog_search_text gin_trgm_ops)"
            )
        )


def downgrade():
    conn = op.get_bind()
    if not sa.inspect(conn).has_table("books"):
        return

    indexes = _index_names(conn)
    for name in (
        "ix_books_catalog_search_trgm",
        "ix_books_catalog_updated_seek",
        "ix_books_catalog_word_count_seek",
        "ix_books_catalog_author_seek",
        "ix_books_catalog_title_seek",
        "ix_books_catalog_series_page",
    ):
        if name in indexes:
            op.drop_index(name, table_name="books")

    columns = {column["name"]: column for column in sa.inspect(conn).get_columns("books")}
    if columns.get("catalog_search_text", {}).get("comment") == _COLUMN_COMMENT:
        op.drop_column("books", "catalog_search_text")
