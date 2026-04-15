"""Add scheduler settings for configurable daily web novel runs.

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-15 00:00:00
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    if not sa.inspect(conn).has_table("scheduler_settings"):
        op.create_table(
            "scheduler_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("web_novel_schedule_hour", sa.Integer(), nullable=True),
            sa.Column("web_novel_schedule_minute", sa.Integer(), nullable=True),
            sa.Column("web_novel_schedule_timezone", sa.String(), nullable=True),
        )


def downgrade():
    conn = op.get_bind()

    if sa.inspect(conn).has_table("scheduler_settings"):
        op.drop_table("scheduler_settings")
