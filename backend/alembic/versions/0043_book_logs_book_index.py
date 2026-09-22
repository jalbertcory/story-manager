"""Index book logs by book and time.

Every scheduled web-novel check appends a log row per book, and the latest-check,
update-history, and delete paths all filter by book_id.

Revision ID: 0043
Revises: 0042
"""

from alembic import op
import sqlalchemy as sa

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

_INDEX = "ix_book_logs_book_id_timestamp"


def upgrade():
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("book_logs")}
    if _INDEX not in existing:
        op.create_index(_INDEX, "book_logs", ["book_id", "timestamp"])


def downgrade():
    op.drop_index(_INDEX, table_name="book_logs")
