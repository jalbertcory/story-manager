"""Optional universes for series and standalone books.

Revision ID: 0041
Revises: 0040
"""

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "universes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False, unique=True),
    )
    op.create_table(
        "universe_series",
        sa.Column("series_key", sa.String(), primary_key=True),
        sa.Column("universe_id", sa.Integer(), sa.ForeignKey("universes.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_universe_series_universe_id", "universe_series", ["universe_id"])
    op.add_column("books", sa.Column("universe_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_books_universe_id", "books", "universes", ["universe_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_books_universe_id", "books", ["universe_id"])


def downgrade():
    op.drop_index("ix_books_universe_id", table_name="books")
    op.drop_constraint("fk_books_universe_id", "books", type_="foreignkey")
    op.drop_column("books", "universe_id")
    op.drop_index("ix_universe_series_universe_id", table_name="universe_series")
    op.drop_table("universe_series")
    op.drop_table("universes")
