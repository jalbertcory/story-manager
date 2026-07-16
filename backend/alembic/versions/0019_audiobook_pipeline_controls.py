"""add resumable audiobook pipeline controls

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-13 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("books", sa.Column("audiobook_stop_after_phase", sa.String(), nullable=True))
    op.add_column(
        "books",
        sa.Column("audiobook_pause_requested", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("books", sa.Column("audiobook_last_error", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("books", "audiobook_last_error")
    op.drop_column("books", "audiobook_pause_requested")
    op.drop_column("books", "audiobook_stop_after_phase")
