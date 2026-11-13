"""Store why a web-novel update check failed.

Failed checks were recorded as a bare ``error`` log entry, so the UI could only
say that a check failed. ``detail`` holds a short reason for those entries.

Revision ID: 0047
Revises: 0046
"""

from alembic import op
import sqlalchemy as sa

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def _has_detail() -> bool:
    return any(column["name"] == "detail" for column in sa.inspect(op.get_bind()).get_columns("book_logs"))


def upgrade():
    if not _has_detail():
        op.add_column("book_logs", sa.Column("detail", sa.Text(), nullable=True))


def downgrade():
    if _has_detail():
        op.drop_column("book_logs", "detail")
