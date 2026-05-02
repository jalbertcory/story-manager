"""allow multiple metadata match candidates

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-28 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def _book_match_unique_constraints(inspector):
    return [
        constraint["name"]
        for constraint in inspector.get_unique_constraints("book_metadata_matches")
        if set(constraint.get("column_names") or []) == {"book_id"} and constraint.get("name")
    ]


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if not inspector.has_table("book_metadata_matches"):
        return

    for constraint_name in _book_match_unique_constraints(inspector):
        op.drop_constraint(constraint_name, "book_metadata_matches", type_="unique")


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if not inspector.has_table("book_metadata_matches"):
        return

    conn.execute(
        sa.text(
            """
            DELETE FROM book_metadata_matches
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM book_metadata_matches
                GROUP BY book_id
            )
            """
        )
    )

    if not _book_match_unique_constraints(inspector):
        op.create_unique_constraint(
            "uq_book_metadata_matches_book_id",
            "book_metadata_matches",
            ["book_id"],
        )
