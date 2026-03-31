"""add user genre tags to books

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-30 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("books"):
        columns = {column["name"] for column in inspector.get_columns("books")}
        if "user_genre_tags" not in columns:
            op.add_column("books", sa.Column("user_genre_tags", sa.JSON(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("books"):
        columns = {column["name"] for column in inspector.get_columns("books")}
        if "user_genre_tags" in columns:
            op.drop_column("books", "user_genre_tags")
