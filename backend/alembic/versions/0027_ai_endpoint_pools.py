"""add ordered AI endpoint pools

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-01 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_CREATED_COLUMN_COMMENT = "story-manager:alembic:0027"


def _columns(conn, table_name: str) -> dict[str, dict]:
    inspector = sa.inspect(conn)
    if not inspector.has_table(table_name):
        return {}
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def upgrade():
    conn = op.get_bind()
    columns = _columns(conn, "audiobook_settings")
    if not columns:
        return

    for name in ("llm_endpoints", "tts_endpoints", "transcription_endpoints"):
        if name not in columns:
            op.add_column(
                "audiobook_settings",
                sa.Column(name, sa.JSON(), nullable=True, comment=_CREATED_COLUMN_COMMENT),
            )

    settings = sa.table(
        "audiobook_settings",
        sa.column("id", sa.Integer),
        sa.column("llm_provider", sa.String),
        sa.column("llm_api_key", sa.String),
        sa.column("llm_base_url", sa.String),
        sa.column("llm_model", sa.String),
        sa.column("tts_provider", sa.String),
        sa.column("tts_api_key", sa.String),
        sa.column("tts_base_url", sa.String),
        sa.column("tts_model", sa.String),
        sa.column("tts_default_voice", sa.String),
        sa.column("transcription_provider", sa.String),
        sa.column("transcription_api_key", sa.String),
        sa.column("transcription_base_url", sa.String),
        sa.column("transcription_model", sa.String),
        sa.column("transcription_language", sa.String),
        sa.column("llm_endpoints", sa.JSON),
        sa.column("tts_endpoints", sa.JSON),
        sa.column("transcription_endpoints", sa.JSON),
    )

    for row in conn.execute(sa.select(settings)).mappings():
        values = {}
        if row["llm_endpoints"] is None:
            values["llm_endpoints"] = [
                {
                    "id": "legacy-llm",
                    "name": "Primary",
                    "provider": row["llm_provider"] or "stub",
                    "api_key": row["llm_api_key"],
                    "base_url": row["llm_base_url"],
                    "model": row["llm_model"],
                }
            ]
        if row["tts_endpoints"] is None:
            values["tts_endpoints"] = [
                {
                    "id": "legacy-tts",
                    "name": "Primary",
                    "provider": row["tts_provider"] or "stub",
                    "api_key": row["tts_api_key"],
                    "base_url": row["tts_base_url"],
                    "model": row["tts_model"],
                    "default_voice": row["tts_default_voice"],
                }
            ]
        if row["transcription_endpoints"] is None:
            values["transcription_endpoints"] = [
                {
                    "id": "legacy-transcription",
                    "name": "Primary",
                    "provider": row["transcription_provider"] or "none",
                    "api_key": row["transcription_api_key"],
                    "base_url": row["transcription_base_url"],
                    "model": row["transcription_model"],
                    "language": row["transcription_language"],
                }
            ]
        if values:
            conn.execute(settings.update().where(settings.c.id == row["id"]).values(**values))


def downgrade():
    conn = op.get_bind()
    columns = _columns(conn, "audiobook_settings")
    for name in ("transcription_endpoints", "tts_endpoints", "llm_endpoints"):
        if columns.get(name, {}).get("comment") == _CREATED_COLUMN_COMMENT:
            op.drop_column("audiobook_settings", name)
