"""store proposal evidence with each metadata candidate

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-12 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

TABLE_NAME = "book_metadata_matches"


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("books"):
        book_columns = {column["name"] for column in inspector.get_columns("books")}
        if "metadata_details" not in book_columns:
            op.add_column("books", sa.Column("metadata_details", sa.JSON(), nullable=True))

    if not inspector.has_table(TABLE_NAME):
        return

    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}
    if "proposed_genre_tags" not in columns:
        op.add_column(TABLE_NAME, sa.Column("proposed_genre_tags", sa.JSON(), nullable=True))
    if "possible_missing_series_books" not in columns:
        op.add_column(TABLE_NAME, sa.Column("possible_missing_series_books", sa.JSON(), nullable=True))
    if "note" not in columns:
        op.add_column(TABLE_NAME, sa.Column("note", sa.Text(), nullable=True))
    if "remote_metadata" not in columns:
        op.add_column(TABLE_NAME, sa.Column("remote_metadata", sa.JSON(), nullable=True))
    if "match_issues" not in columns:
        op.add_column(TABLE_NAME, sa.Column("match_issues", sa.JSON(), nullable=True))

    if not inspector.has_table("metadata_proposals"):
        return

    matches = sa.table(
        TABLE_NAME,
        sa.column("id", sa.Integer),
        sa.column("proposed_genre_tags", sa.JSON),
        sa.column("possible_missing_series_books", sa.JSON),
        sa.column("note", sa.Text),
    )
    proposals = sa.table(
        "metadata_proposals",
        sa.column("match_id", sa.Integer),
        sa.column("proposed_genre_tags", sa.JSON),
        sa.column("possible_missing_series_books", sa.JSON),
        sa.column("note", sa.Text),
    )
    rows = conn.execute(
        sa.select(
            proposals.c.match_id,
            proposals.c.proposed_genre_tags,
            proposals.c.possible_missing_series_books,
            proposals.c.note,
        ).where(proposals.c.match_id.is_not(None))
    )
    for row in rows:
        conn.execute(
            matches.update()
            .where(matches.c.id == row.match_id)
            .values(
                proposed_genre_tags=row.proposed_genre_tags,
                possible_missing_series_books=row.possible_missing_series_books,
                note=row.note,
            )
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if inspector.has_table(TABLE_NAME):
        columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}
        for column_name in (
            "match_issues",
            "remote_metadata",
            "note",
            "possible_missing_series_books",
            "proposed_genre_tags",
        ):
            if column_name in columns:
                op.drop_column(TABLE_NAME, column_name)
    if inspector.has_table("books"):
        book_columns = {column["name"] for column in inspector.get_columns("books")}
        if "metadata_details" in book_columns:
            op.drop_column("books", "metadata_details")
