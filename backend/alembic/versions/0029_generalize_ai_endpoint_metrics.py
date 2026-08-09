"""generalize endpoint metrics to every AI capability

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-08 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

_OLD_TABLE = "llm_endpoint_request_metrics"
_TABLE = "ai_endpoint_request_metrics"
_OLD_INDEX = "ix_llm_endpoint_metrics_settings_endpoint_created"
_INDEX = "ix_ai_endpoint_metrics_settings_capability_endpoint_created"
_OLD_SUCCESS_INDEX = "ix_llm_endpoint_request_metrics_success"
_SUCCESS_INDEX = "ix_ai_endpoint_request_metrics_success"
_COLUMN_COMMENT = "story-manager:alembic:0029"
_TABLE_COMMENT = "story-manager:alembic:0028"


def _index_names(conn, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(conn).get_indexes(table_name)}


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if inspector.has_table(_OLD_TABLE) and not inspector.has_table(_TABLE):
        op.rename_table(_OLD_TABLE, _TABLE)

    inspector = sa.inspect(conn)
    if not inspector.has_table(_TABLE):
        return

    columns = {column["name"]: column for column in inspector.get_columns(_TABLE)}
    if "capability" not in columns:
        op.add_column(
            _TABLE,
            sa.Column(
                "capability",
                sa.String(),
                nullable=False,
                server_default="llm",
                comment=_COLUMN_COMMENT,
            ),
        )
        op.alter_column(_TABLE, "capability", server_default=None)

    indexes = _index_names(conn, _TABLE)
    if _OLD_INDEX in indexes:
        op.drop_index(_OLD_INDEX, table_name=_TABLE)
    if _INDEX not in indexes:
        op.create_index(
            _INDEX,
            _TABLE,
            ["settings_id", "capability", "endpoint_id", "created_at"],
            unique=False,
        )
    if _OLD_SUCCESS_INDEX in indexes:
        op.drop_index(_OLD_SUCCESS_INDEX, table_name=_TABLE)
    if _SUCCESS_INDEX not in indexes:
        op.create_index(_SUCCESS_INDEX, _TABLE, ["success"], unique=False)


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(_TABLE):
        return

    indexes = _index_names(conn, _TABLE)
    if _INDEX in indexes:
        op.drop_index(_INDEX, table_name=_TABLE)
    if _OLD_INDEX not in indexes:
        op.create_index(
            _OLD_INDEX,
            _TABLE,
            ["settings_id", "endpoint_id", "created_at"],
            unique=False,
        )
    if _SUCCESS_INDEX in indexes:
        op.drop_index(_SUCCESS_INDEX, table_name=_TABLE)
    if _OLD_SUCCESS_INDEX not in indexes:
        op.create_index(_OLD_SUCCESS_INDEX, _TABLE, ["success"], unique=False)

    columns = {column["name"]: column for column in sa.inspect(conn).get_columns(_TABLE)}
    if columns.get("capability", {}).get("comment") == _COLUMN_COMMENT:
        op.drop_column(_TABLE, "capability")

    try:
        table_comment = sa.inspect(conn).get_table_comment(_TABLE).get("text")
    except NotImplementedError:
        table_comment = None
    if table_comment == _TABLE_COMMENT and not sa.inspect(conn).has_table(_OLD_TABLE):
        op.rename_table(_TABLE, _OLD_TABLE)
