"""track the human audiobook rebuild pipeline version

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-27 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if inspector.has_table("imported_audiobooks"):
        columns = {column["name"] for column in inspector.get_columns("imported_audiobooks")}
        if "pipeline_version" not in columns:
            op.add_column(
                "imported_audiobooks",
                sa.Column("pipeline_version", sa.Integer(), server_default="0", nullable=False),
            )
    if inspector.has_table("imported_audiobook_tracks"):
        columns = {column["name"] for column in inspector.get_columns("imported_audiobook_tracks")}
        if "match_method" not in columns:
            op.add_column("imported_audiobook_tracks", sa.Column("match_method", sa.String(), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if inspector.has_table("imported_audiobook_tracks"):
        columns = {column["name"] for column in inspector.get_columns("imported_audiobook_tracks")}
        if "match_method" in columns:
            op.drop_column("imported_audiobook_tracks", "match_method")
    if inspector.has_table("imported_audiobooks"):
        columns = {column["name"] for column in inspector.get_columns("imported_audiobooks")}
        if "pipeline_version" in columns:
            op.drop_column("imported_audiobooks", "pipeline_version")
