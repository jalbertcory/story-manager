"""add series index to books

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("books"):
        columns = {column["name"] for column in inspector.get_columns("books")}
        if "series_index" not in columns:
            op.add_column("books", sa.Column("series_index", sa.Numeric(6, 2), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("books"):
        columns = {column["name"] for column in inspector.get_columns("books")}
        if "series_index" in columns:
            op.drop_column("books", "series_index")
