"""lock audiobook TTS provider per book and series

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-25 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def _column_names(conn, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(conn).get_columns(table_name)}


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table("books"):
        return
    if "audiobook_tts_provider" not in _column_names(conn, "books"):
        op.add_column("books", sa.Column("audiobook_tts_provider", sa.String(), nullable=True))

    if not inspector.has_table("audiobook_characters"):
        return

    books = sa.table(
        "books",
        sa.column("id", sa.Integer),
        sa.column("series", sa.String),
        sa.column("audiobook_tts_provider", sa.String),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    characters = sa.table(
        "audiobook_characters",
        sa.column("book_id", sa.Integer),
        sa.column("tts_voice_provider", sa.String),
    )

    # Backfill only unambiguous books. A mixed historical roster remains
    # unlocked so the application can require an explicit user choice.
    rows = conn.execute(
        sa.select(characters.c.book_id, characters.c.tts_voice_provider)
        .where(characters.c.tts_voice_provider.is_not(None))
        .distinct()
    ).all()
    providers_by_book: dict[int, set[str]] = {}
    for book_id, provider in rows:
        normalized = provider.strip().lower()
        if normalized:
            providers_by_book.setdefault(book_id, set()).add(normalized)
    for book_id, providers in providers_by_book.items():
        if len(providers) == 1:
            conn.execute(
                books.update()
                .where(books.c.id == book_id, books.c.audiobook_tts_provider.is_(None))
                .values(audiobook_tts_provider=next(iter(providers)))
            )

    # A provider already proven by one book becomes the default lock for its
    # unconfigured series siblings. Conflicting historical series are left
    # alone and surfaced by runtime validation.
    locked = conn.execute(
        sa.select(books.c.series, books.c.audiobook_tts_provider).where(
            books.c.series.is_not(None),
            books.c.audiobook_tts_provider.is_not(None),
            books.c.deleted_at.is_(None),
        )
    ).all()
    providers_by_series: dict[str, set[str]] = {}
    display_name_by_key: dict[str, str] = {}
    for series, provider in locked:
        normalized = provider.strip().lower()
        if not normalized:
            continue
        key = series.casefold()
        display_name_by_key.setdefault(key, series)
        providers_by_series.setdefault(key, set()).add(normalized)
    for key, providers in providers_by_series.items():
        if len(providers) == 1:
            conn.execute(
                books.update()
                .where(
                    sa.func.lower(books.c.series) == display_name_by_key[key].lower(),
                    books.c.audiobook_tts_provider.is_(None),
                    books.c.deleted_at.is_(None),
                )
                .values(audiobook_tts_provider=next(iter(providers)))
            )


def downgrade():
    conn = op.get_bind()
    if sa.inspect(conn).has_table("books") and "audiobook_tts_provider" in _column_names(conn, "books"):
        op.drop_column("books", "audiobook_tts_provider")
