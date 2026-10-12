"""replace the absolute TTS voice-similarity threshold with a drift margin

Local TTS workers now calibrate each stored voice's own similarity range and
reject takes that fall ``margin`` standard deviations below it or sound closer
to another cast voice. An absolute cosine threshold no longer has a meaning
across speaker-verification models, so the setting becomes a margin in standard
deviations. Existing rows keep "disabled" (a threshold at or below zero) and
otherwise move to the new default.

Revision ID: 0044
Revises: 0043
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

_TABLE = "audiobook_settings"
_OLD = "tts_voice_similarity_threshold"
_NEW = "tts_voice_drift_margin"
_OLD_DEFAULT = 0.45
_NEW_DEFAULT = 3.0


def _column_names(conn) -> set[str]:
    return {column["name"] for column in sa.inspect(conn).get_columns(_TABLE)}


def _settings(column: str) -> sa.TableClause:
    return sa.table(_TABLE, sa.column(column, sa.Float))


def _remap(conn, column: str, enabled_value: float) -> None:
    """Keep disabled rows at 0 and move every enabled row to ``enabled_value``."""
    settings = _settings(column)
    value = settings.c[column]
    conn.execute(settings.update().where(sa.or_(value.is_(None), value > 0)).values({column: enabled_value}))
    conn.execute(settings.update().where(value <= 0).values({column: 0.0}))


def upgrade():
    conn = op.get_bind()
    if not sa.inspect(conn).has_table(_TABLE):
        return
    columns = _column_names(conn)
    if _NEW not in columns:
        if _OLD in columns:
            op.alter_column(_TABLE, _OLD, new_column_name=_NEW, existing_type=sa.Float(), existing_nullable=False)
        else:
            op.add_column(
                _TABLE,
                sa.Column(_NEW, sa.Float(), nullable=False, server_default=str(_NEW_DEFAULT)),
            )
    _remap(conn, _NEW, _NEW_DEFAULT)
    op.alter_column(_TABLE, _NEW, existing_type=sa.Float(), existing_nullable=False, server_default=str(_NEW_DEFAULT))


def downgrade():
    conn = op.get_bind()
    if not sa.inspect(conn).has_table(_TABLE):
        return
    columns = _column_names(conn)
    if _NEW not in columns:
        return
    if _OLD in columns:
        op.drop_column(_TABLE, _OLD)
    op.alter_column(_TABLE, _NEW, new_column_name=_OLD, existing_type=sa.Float(), existing_nullable=False)
    _remap(conn, _OLD, _OLD_DEFAULT)
    op.alter_column(_TABLE, _OLD, existing_type=sa.Float(), existing_nullable=False, server_default=str(_OLD_DEFAULT))
