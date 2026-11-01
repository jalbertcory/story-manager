"""store an admin session epoch so logout revokes issued session cookies

Admin session cookies are stateless signed tokens. Each token now carries the
session epoch current when it was issued, and logout bumps the stored epoch so
every earlier cookie stops validating.

Revision ID: 0045
Revises: 0044
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

_TABLE = "admin_auth_state"


def upgrade():
    conn = op.get_bind()
    if not sa.inspect(conn).has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    state = sa.table(_TABLE, sa.column("id", sa.Integer), sa.column("session_epoch", sa.Integer))
    exists = conn.execute(sa.select(state.c.id).where(state.c.id == 1)).fetchone()
    if not exists:
        conn.execute(state.insert().values(id=1, session_epoch=0))


def downgrade():
    conn = op.get_bind()
    if sa.inspect(conn).has_table(_TABLE):
        op.drop_table(_TABLE)
