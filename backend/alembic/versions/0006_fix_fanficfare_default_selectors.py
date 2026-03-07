"""Seed FanFicFare Defaults cleaning config and fix selectors (underscore to hyphen)

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-03 00:00:00

The cleaning_configs table was historically created by SQLAlchemy's create_all()
at app startup rather than via a migration. This migration creates it if absent
(fresh installs), then seeds / fixes the FanFicFare Defaults row.

"""

import json

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

CORRECT_SELECTORS = ["div.author-note", "p.author-note"]

cleaning_configs = sa.table(
    "cleaning_configs",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("url_pattern", sa.String),
    sa.column("chapter_selectors", sa.JSON),
    sa.column("content_selectors", sa.JSON),
)


def upgrade():
    conn = op.get_bind()

    if not sa.inspect(conn).has_table("cleaning_configs"):
        op.create_table(
            "cleaning_configs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False, unique=True),
            sa.Column("url_pattern", sa.String(), nullable=False),
            sa.Column("chapter_selectors", sa.JSON(), nullable=True),
            sa.Column("content_selectors", sa.JSON(), nullable=True),
        )

    rows = conn.execute(
        sa.select(cleaning_configs.c.id, cleaning_configs.c.content_selectors).where(
            cleaning_configs.c.name == "FanFicFare Defaults"
        )
    ).fetchall()

    if not rows:
        conn.execute(
            cleaning_configs.insert().values(
                name="FanFicFare Defaults",
                url_pattern=".*",
                chapter_selectors=[],
                content_selectors=CORRECT_SELECTORS,
            )
        )
    else:
        for row_id, raw in rows:
            selectors = raw if isinstance(raw, list) else json.loads(raw or "[]")
            fixed = [s.replace("author_note", "author-note") for s in selectors]
            if fixed != list(selectors):
                conn.execute(cleaning_configs.update().where(cleaning_configs.c.id == row_id).values(content_selectors=fixed))


def downgrade():
    conn = op.get_bind()
    rows = conn.execute(
        sa.select(cleaning_configs.c.id, cleaning_configs.c.content_selectors).where(
            cleaning_configs.c.name == "FanFicFare Defaults"
        )
    ).fetchall()
    for row_id, raw in rows:
        selectors = raw if isinstance(raw, list) else json.loads(raw or "[]")
        reverted = [s.replace("author-note", "author_note") for s in selectors]
        if reverted != list(selectors):
            conn.execute(cleaning_configs.update().where(cleaning_configs.c.id == row_id).values(content_selectors=reverted))
