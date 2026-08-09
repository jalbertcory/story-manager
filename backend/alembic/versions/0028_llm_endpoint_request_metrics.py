"""add LLM endpoint request metrics

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-08 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_TABLE_COMMENT = "story-manager:alembic:0028"


def upgrade():
    conn = op.get_bind()
    if sa.inspect(conn).has_table("llm_endpoint_request_metrics"):
        return

    op.create_table(
        "llm_endpoint_request_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("settings_id", sa.Integer(), nullable=False),
        sa.Column("endpoint_id", sa.String(), nullable=False),
        sa.Column("endpoint_name", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("error_type", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["settings_id"],
            ["audiobook_settings.id"],
            name="fk_llm_endpoint_request_metrics_settings_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment=_TABLE_COMMENT,
    )
    op.create_index(
        "ix_llm_endpoint_metrics_settings_endpoint_created",
        "llm_endpoint_request_metrics",
        ["settings_id", "endpoint_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_llm_endpoint_request_metrics_success",
        "llm_endpoint_request_metrics",
        ["success"],
        unique=False,
    )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table("llm_endpoint_request_metrics"):
        return
    try:
        comment = inspector.get_table_comment("llm_endpoint_request_metrics").get("text")
    except NotImplementedError:
        comment = None
    if comment == _TABLE_COMMENT:
        op.drop_table("llm_endpoint_request_metrics")
