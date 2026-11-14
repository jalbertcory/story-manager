"""Add notification webhooks and series gap/release findings.

Both tables are new; nothing existing is rewritten. Each is created only when
absent so the migration is safe to re-run against a partially upgraded database.

Revision ID: 0049
Revises: 0048
"""

from alembic import op
import sqlalchemy as sa

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

_WEBHOOKS = "notification_webhooks"
_FINDINGS = "series_findings"


def upgrade():
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table(_WEBHOOKS):
        op.create_table(
            _WEBHOOKS,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("format", sa.String(), nullable=False, server_default="json"),
            sa.Column("events", sa.JSON(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_delivery_status", sa.String(), nullable=True),
            sa.Column("last_delivery_error", sa.Text(), nullable=True),
        )
        op.create_index("ix_notification_webhooks_id", _WEBHOOKS, ["id"])

    if not inspector.has_table(_FINDINGS):
        op.create_table(
            _FINDINGS,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("finding_key", sa.String(), nullable=False),
            sa.Column("series_name", sa.String(), nullable=False),
            sa.Column("author", sa.String(), nullable=True),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("series_index", sa.Numeric(6, 2), nullable=True),
            sa.Column("published_date", sa.String(), nullable=True),
            sa.Column("release_date", sa.Date(), nullable=True),
            sa.Column("source", sa.String(), nullable=True),
            sa.Column("remote_url", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="open"),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("kind IN ('gap', 'release')", name="ck_series_findings_kind"),
            sa.CheckConstraint("status IN ('open', 'dismissed')", name="ck_series_findings_status"),
            sa.UniqueConstraint("finding_key", name="uq_series_findings_finding_key"),
        )
        op.create_index("ix_series_findings_id", _FINDINGS, ["id"])
        op.create_index("ix_series_findings_kind", _FINDINGS, ["kind"])
        op.create_index("ix_series_findings_series_name", _FINDINGS, ["series_name"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_FINDINGS):
        op.drop_table(_FINDINGS)
    if inspector.has_table(_WEBHOOKS):
        op.drop_table(_WEBHOOKS)
