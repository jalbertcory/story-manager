"""make audiobook TTS configuration provider neutral

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-17 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def _column_names(conn, table_name: str) -> set[str]:
    inspector = sa.inspect(conn)
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    conn = op.get_bind()

    settings_columns = _column_names(conn, "audiobook_settings")
    if "omnivoice_endpoint" in settings_columns and "tts_base_url" not in settings_columns:
        op.alter_column(
            "audiobook_settings",
            "omnivoice_endpoint",
            new_column_name="tts_base_url",
        )
        settings_columns.remove("omnivoice_endpoint")
        settings_columns.add("tts_base_url")

    for name in ("tts_provider", "tts_api_key", "tts_model", "tts_default_voice"):
        if name not in settings_columns:
            op.add_column("audiobook_settings", sa.Column(name, sa.String(), nullable=True))

    audiobook_settings = sa.table(
        "audiobook_settings",
        sa.column("tts_provider", sa.String()),
        sa.column("tts_base_url", sa.String()),
    )
    conn.execute(
        audiobook_settings.update()
        .where(
            audiobook_settings.c.tts_provider.is_(None),
            audiobook_settings.c.tts_base_url.is_not(None),
        )
        .values(tts_provider="omnivoice")
    )
    conn.execute(
        audiobook_settings.update()
        .where(audiobook_settings.c.tts_provider.is_(None))
        .values(tts_provider="stub")
    )

    for table_name in ("audiobook_characters", "audiobook_series_characters"):
        columns = _column_names(conn, table_name)
        if not columns:
            continue
        if "voice_design_prompt" in columns and "voice_prompt" not in columns:
            op.alter_column(
                table_name,
                "voice_design_prompt",
                new_column_name="voice_prompt",
            )
            columns.remove("voice_design_prompt")
            columns.add("voice_prompt")
        if "tts_voice_id" not in columns:
            op.add_column(table_name, sa.Column("tts_voice_id", sa.String(), nullable=True))


def downgrade():
    conn = op.get_bind()

    for table_name in ("audiobook_series_characters", "audiobook_characters"):
        columns = _column_names(conn, table_name)
        if not columns:
            continue
        if "tts_voice_id" in columns:
            op.drop_column(table_name, "tts_voice_id")
        if "voice_prompt" in columns and "voice_design_prompt" not in columns:
            op.alter_column(
                table_name,
                "voice_prompt",
                new_column_name="voice_design_prompt",
            )

    settings_columns = _column_names(conn, "audiobook_settings")
    if not settings_columns:
        return

    if "tts_provider" in settings_columns and "tts_base_url" in settings_columns:
        audiobook_settings = sa.table(
            "audiobook_settings",
            sa.column("tts_provider", sa.String()),
            sa.column("tts_base_url", sa.String()),
        )
        conn.execute(
            audiobook_settings.update()
            .where(
                audiobook_settings.c.tts_provider.is_not(None),
                audiobook_settings.c.tts_provider != "omnivoice",
            )
            .values(tts_base_url=None)
        )

    for name in ("tts_default_voice", "tts_model", "tts_api_key", "tts_provider"):
        if name in settings_columns:
            op.drop_column("audiobook_settings", name)

    if "tts_base_url" in settings_columns and "omnivoice_endpoint" not in settings_columns:
        op.alter_column(
            "audiobook_settings",
            "tts_base_url",
            new_column_name="omnivoice_endpoint",
        )
