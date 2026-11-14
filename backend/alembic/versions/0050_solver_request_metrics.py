"""Record each Cloudflare solver request so solvers can be compared over time.

Revision ID: 0050
Revises: 0049
"""

from alembic import op
import sqlalchemy as sa

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

TABLE = "solver_request_metrics"
INDEX = "ix_solver_request_metrics_site_solver_created"


def upgrade():
    if sa.inspect(op.get_bind()).has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("site", sa.String(), nullable=False),
        sa.Column("solver_url", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("error_type", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(INDEX, TABLE, ["site", "solver_url", "created_at"])


def downgrade():
    if sa.inspect(op.get_bind()).has_table(TABLE):
        op.drop_table(TABLE)
