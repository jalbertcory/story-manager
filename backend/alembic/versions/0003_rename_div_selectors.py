"""Rename div_selectors to content_selectors on books table

Revision ID: 0003
Revises: 0002
Create Date: 2026-02-27 00:00:00

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("books", schema=None) as batch_op:
        batch_op.alter_column("div_selectors", new_column_name="content_selectors")


def downgrade():
    with op.batch_alter_table("books", schema=None) as batch_op:
        batch_op.alter_column("content_selectors", new_column_name="div_selectors")
