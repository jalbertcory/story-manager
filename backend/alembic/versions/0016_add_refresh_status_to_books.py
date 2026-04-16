"""add refresh_status to books

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-16 00:00:00
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if not inspector.has_table("books"):
        return

    columns = {column["name"] for column in inspector.get_columns("books")}
    if "refresh_status" not in columns:
        op.add_column("books", sa.Column("refresh_status", sa.String(), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if not inspector.has_table("books"):
        return

    columns = {column["name"] for column in inspector.get_columns("books")}
    if "refresh_status" in columns:
        op.drop_column("books", "refresh_status")
