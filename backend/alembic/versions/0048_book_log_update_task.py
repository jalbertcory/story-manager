"""Tie each update-check log entry to the scheduled run that wrote it.

Run results were matched to a run by timestamp, so a manual check made just
before or during a scheduled run was counted as part of it. New entries store
the run explicitly. Existing entries are matched once, by the same timestamp
window the application used until now, so run history stays as it was.

Revision ID: 0048
Revises: 0047
"""

from alembic import op
import sqlalchemy as sa

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

INDEX = "ix_book_logs_update_task_id"
FOREIGN_KEY = "fk_book_logs_update_task_id_update_tasks"


def _has_column() -> bool:
    return any(column["name"] == "update_task_id" for column in sa.inspect(op.get_bind()).get_columns("book_logs"))


def upgrade():
    if _has_column():
        return
    op.add_column("book_logs", sa.Column("update_task_id", sa.Integer(), nullable=True))
    if not sa.inspect(op.get_bind()).has_table("update_tasks"):
        return
    op.create_foreign_key(FOREIGN_KEY, "book_logs", "update_tasks", ["update_task_id"], ["id"], ondelete="SET NULL")
    op.create_index(INDEX, "book_logs", ["update_task_id"])
    op.execute("""
        UPDATE book_logs
        SET update_task_id = (
            SELECT t.id
            FROM update_tasks t
            WHERE t.started_at IS NOT NULL
              AND t.completed_at IS NOT NULL
              AND book_logs.timestamp >= t.started_at - interval '1 second'
              AND book_logs.timestamp <= t.completed_at
            ORDER BY t.started_at DESC
            LIMIT 1
        )
        WHERE update_task_id IS NULL
          AND entry_type IN ('checked', 'updated', 'error')
        """)


def downgrade():
    if not _has_column():
        return
    inspector = sa.inspect(op.get_bind())
    if any(index["name"] == INDEX for index in inspector.get_indexes("book_logs")):
        op.drop_index(INDEX, table_name="book_logs")
    if any(key["name"] == FOREIGN_KEY for key in inspector.get_foreign_keys("book_logs")):
        op.drop_constraint(FOREIGN_KEY, "book_logs", type_="foreignkey")
    op.drop_column("book_logs", "update_task_id")
