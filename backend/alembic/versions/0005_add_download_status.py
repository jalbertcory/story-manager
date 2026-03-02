"""Add download_status column to books table

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-01 00:00:00

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("books", sa.Column("download_status", sa.String(), nullable=True))


def downgrade():
    op.drop_column("books", "download_status")
