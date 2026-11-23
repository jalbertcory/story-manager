"""Add the narration pronunciation lexicon.

The table is new; nothing existing is rewritten. It is created only when absent
so the migration is safe to re-run against a partially upgraded database.

Revision ID: 0053
Revises: 0052
"""

from alembic import op
import sqlalchemy as sa

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

_TABLE = "audiobook_pronunciations"


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=True),
        sa.Column("series_name", sa.String(), nullable=True),
        sa.Column("term", sa.String(), nullable=False),
        sa.Column("spoken", sa.String(), nullable=False),
        sa.Column("case_sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("book_id IS NULL OR series_name IS NULL", name="ck_audiobook_pronunciations_scope"),
        sa.CheckConstraint("length(trim(term)) > 0", name="ck_audiobook_pronunciations_term"),
        sa.CheckConstraint("length(trim(spoken)) > 0", name="ck_audiobook_pronunciations_spoken"),
    )
    op.create_index("ix_audiobook_pronunciations_id", _TABLE, ["id"])
    op.create_index("ix_audiobook_pronunciations_book_id", _TABLE, ["book_id"])
    op.create_index("ix_audiobook_pronunciations_series_name", _TABLE, ["series_name"])


def downgrade():
    if sa.inspect(op.get_bind()).has_table(_TABLE):
        op.drop_table(_TABLE)
