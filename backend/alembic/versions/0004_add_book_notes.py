"""Add notes column to books table

Revision ID: 0004
Revises: 0003
Create Date: 2026-02-27 00:00:00

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("books", sa.Column("notes", sa.String(), nullable=True))


def downgrade():
    op.drop_column("books", "notes")
