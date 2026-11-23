"""Add story recaps.

The table is new; nothing existing is rewritten. It is created only when absent
so the migration is safe to re-run against a partially upgraded database.

Revision ID: 0054
Revises: 0053
"""

from alembic import op
import sqlalchemy as sa

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None

_TABLE = "story_recaps"


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("recap", sa.Text(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("covered_book_ids", sa.JSON(), nullable=True),
        sa.Column("llm_model", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("book_id", "kind", name="uq_story_recaps_book_kind"),
        sa.CheckConstraint("kind IN ('book', 'story_so_far')", name="ck_story_recaps_kind"),
    )
    op.create_index("ix_story_recaps_id", _TABLE, ["id"])
    op.create_index("ix_story_recaps_book_id", _TABLE, ["book_id"])


def downgrade():
    if sa.inspect(op.get_bind()).has_table(_TABLE):
        op.drop_table(_TABLE)
