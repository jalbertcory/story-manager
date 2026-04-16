"""add source tags to books

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-16 00:00:00
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


SCRIBBLEHUB_GENRES = {
    "Action",
    "Adult",
    "Adventure",
    "Boys Love",
    "Comedy",
    "Drama",
    "Ecchi",
    "Fanfiction",
    "Fantasy",
    "Gender Bender",
    "Girls Love",
    "Harem",
    "Historical",
    "Horror",
    "Isekai",
    "Josei",
    "LitRPG",
    "Martial Arts",
    "Mature",
    "Mecha",
    "Mystery",
    "Psychological",
    "Romance",
    "School Life",
    "Sci-fi",
    "Seinen",
    "Shoujo",
    "Shounen",
    "Slice of Life",
    "Smut",
    "Sports",
    "Supernatural",
    "Tragedy",
    "Wuxia",
    "Xianxia",
    "Yaoi",
    "Yuri",
}


def _normalize_tags(tags):
    normalized = []
    seen = set()
    for raw_tag in tags or []:
        if not isinstance(raw_tag, str):
            continue
        cleaned = raw_tag.strip()
        if not cleaned:
            continue
        folded = cleaned.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        normalized.append(cleaned)
    return normalized


def _split_scribblehub_tags(tags):
    genre_lookup = {tag.casefold() for tag in SCRIBBLEHUB_GENRES}
    genres = []
    source_tags = []
    for tag in _normalize_tags(tags):
        if tag.casefold() in genre_lookup:
            genres.append(tag)
        else:
            source_tags.append(tag)
    return genres, source_tags


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if not inspector.has_table("books"):
        return

    columns = {column["name"] for column in inspector.get_columns("books")}
    if "source_tags" not in columns:
        op.add_column("books", sa.Column("source_tags", sa.JSON(), nullable=True))

    books = sa.table(
        "books",
        sa.column("id", sa.Integer),
        sa.column("source_url", sa.String),
        sa.column("genre_tags", sa.JSON),
        sa.column("source_tags", sa.JSON),
    )

    rows = conn.execute(
        sa.select(books.c.id, books.c.source_url, books.c.genre_tags, books.c.source_tags).where(
            books.c.genre_tags.is_not(None)
        )
    ).fetchall()

    for row in rows:
        if row.source_tags:
            continue
        source_url = row.source_url or ""
        if "scribblehub.com" not in source_url.lower():
            continue
        genres, source_tags = _split_scribblehub_tags(row.genre_tags)
        if not source_tags:
            continue
        conn.execute(
            books.update()
            .where(books.c.id == row.id)
            .values(
                genre_tags=genres,
                source_tags=source_tags,
            )
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if not inspector.has_table("books"):
        return

    columns = {column["name"] for column in inspector.get_columns("books")}
    if "source_tags" not in columns:
        return

    books = sa.table(
        "books",
        sa.column("id", sa.Integer),
        sa.column("source_url", sa.String),
        sa.column("genre_tags", sa.JSON),
        sa.column("source_tags", sa.JSON),
    )

    rows = conn.execute(
        sa.select(books.c.id, books.c.source_url, books.c.genre_tags, books.c.source_tags).where(
            books.c.source_tags.is_not(None)
        )
    ).fetchall()

    for row in rows:
        source_url = row.source_url or ""
        if "scribblehub.com" not in source_url.lower():
            continue
        merged = _normalize_tags([*(row.genre_tags or []), *(row.source_tags or [])])
        conn.execute(books.update().where(books.c.id == row.id).values(genre_tags=merged))

    op.drop_column("books", "source_tags")
