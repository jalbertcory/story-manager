"""retire the audiobook publication error state

Nothing in the application sets ``audiobook_publication_state = 'error'`` or
reads ``audiobook_publication_error``: a failed narration run is reported by
``audiobook_pipeline_status``. Only migrations 0023 and 0033 ever wrote either
value, so a few existing books may still carry them.

Those books move to the state ingestion would give them: ``partial`` when a
chapter has finished audio, otherwise ``processing``. The error state is then
removed from the check constraint and the unused message column is dropped.

Downgrade restores the column and the constraint value but not the data: the
messages were never shown, and the books keep their remapped state.

Revision ID: 0052
Revises: 0051
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

TABLE = "books"
STATE_COLUMN = "audiobook_publication_state"
ERROR_COLUMN = "audiobook_publication_error"
CONSTRAINT = "ck_books_audiobook_publication_state"
STATES = ("processing", "partial", "complete", "stale")
LEGACY_STATES = (*STATES, "error")

_books = sa.table(
    TABLE,
    sa.column("id", sa.Integer),
    sa.column(STATE_COLUMN, sa.String),
)
_chapters = sa.table(
    "audiobook_chapters",
    sa.column("book_id", sa.Integer),
    sa.column("generation_state", sa.String),
)


def _replace_constraint(states: tuple[str, ...]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {constraint["name"] for constraint in inspector.get_check_constraints(TABLE)}
    if CONSTRAINT in existing:
        op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    allowed = ", ".join(f"'{state}'" for state in states)
    op.create_check_constraint(CONSTRAINT, TABLE, f"{STATE_COLUMN} IN ({allowed})")


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(TABLE):
        return

    in_error = _books.c.audiobook_publication_state == "error"
    if inspector.has_table("audiobook_chapters"):
        has_ready_chapter = (
            sa.select(_chapters.c.book_id)
            .where(_chapters.c.book_id == _books.c.id, _chapters.c.generation_state == "ready")
            .exists()
        )
        conn.execute(_books.update().where(in_error, has_ready_chapter).values(audiobook_publication_state="partial"))
    conn.execute(_books.update().where(in_error).values(audiobook_publication_state="processing"))

    _replace_constraint(STATES)
    if ERROR_COLUMN in {column["name"] for column in inspector.get_columns(TABLE)}:
        op.drop_column(TABLE, ERROR_COLUMN)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return
    if ERROR_COLUMN not in {column["name"] for column in inspector.get_columns(TABLE)}:
        op.add_column(TABLE, sa.Column(ERROR_COLUMN, sa.Text(), nullable=True))
    _replace_constraint(LEGACY_STATES)
