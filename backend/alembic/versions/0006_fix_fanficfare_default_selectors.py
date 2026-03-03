"""Seed FanFicFare Defaults cleaning config and fix selectors (underscore to hyphen)

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-03 00:00:00

"""

import json

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

CORRECT_SELECTORS = ["div.author-note", "p.author-note"]


def upgrade():
    conn = op.get_bind()
    rows = conn.execute(
        text("SELECT id, content_selectors FROM cleaning_configs WHERE name = 'FanFicFare Defaults'")
    ).fetchall()

    if not rows:
        conn.execute(
            text(
                "INSERT INTO cleaning_configs (name, url_pattern, chapter_selectors, content_selectors)"
                " VALUES (:name, :url_pattern, :chapter_selectors, :content_selectors)"
            ),
            {
                "name": "FanFicFare Defaults",
                "url_pattern": ".*",
                "chapter_selectors": json.dumps([]),
                "content_selectors": json.dumps(CORRECT_SELECTORS),
            },
        )
    else:
        for row_id, raw in rows:
            selectors = raw if isinstance(raw, list) else json.loads(raw or "[]")
            fixed = [s.replace("author_note", "author-note") for s in selectors]
            if fixed != list(selectors):
                conn.execute(
                    text("UPDATE cleaning_configs SET content_selectors = :sel WHERE id = :id"),
                    {"sel": json.dumps(fixed), "id": row_id},
                )


def downgrade():
    conn = op.get_bind()
    rows = conn.execute(
        text("SELECT id, content_selectors FROM cleaning_configs WHERE name = 'FanFicFare Defaults'")
    ).fetchall()
    for row_id, raw in rows:
        selectors = raw if isinstance(raw, list) else json.loads(raw or "[]")
        reverted = [s.replace("author-note", "author_note") for s in selectors]
        if reverted != list(selectors):
            conn.execute(
                text("UPDATE cleaning_configs SET content_selectors = :sel WHERE id = :id"),
                {"sel": json.dumps(reverted), "id": row_id},
            )
