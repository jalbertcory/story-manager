"""add processing job request correlation

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-09 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

TABLE_NAME = "processing_jobs"
COLUMN_NAME = "request_id"
INDEX_NAME = "ix_processing_jobs_request_id"


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(TABLE_NAME):
        return

    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}
    if COLUMN_NAME not in columns:
        op.add_column(TABLE_NAME, sa.Column(COLUMN_NAME, sa.String(length=64), nullable=True))

    jobs = sa.table(
        TABLE_NAME,
        sa.column("id", sa.Integer),
        sa.column(COLUMN_NAME, sa.String(length=64)),
    )
    conn.execute(
        jobs.update()
        .where(jobs.c.request_id.is_(None))
        .values(request_id=sa.literal("legacy-") + sa.cast(jobs.c.id, sa.String()))
    )
    op.alter_column(TABLE_NAME, COLUMN_NAME, existing_type=sa.String(length=64), nullable=False)

    indexes = {index["name"] for index in sa.inspect(conn).get_indexes(TABLE_NAME)}
    if INDEX_NAME not in indexes:
        op.create_index(INDEX_NAME, TABLE_NAME, [COLUMN_NAME])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(TABLE_NAME):
        return
    indexes = {index["name"] for index in inspector.get_indexes(TABLE_NAME)}
    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
    columns = {column["name"] for column in sa.inspect(conn).get_columns(TABLE_NAME)}
    if COLUMN_NAME in columns:
        op.drop_column(TABLE_NAME, COLUMN_NAME)
