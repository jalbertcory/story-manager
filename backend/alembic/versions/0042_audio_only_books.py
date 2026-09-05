"""Allow library books whose source is an audiobook.

Revision ID: 0042
Revises: 0041
"""

from alembic import op
import sqlalchemy as sa

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE sourcetype ADD VALUE IF NOT EXISTS 'audiobook'")
    else:
        with op.batch_alter_table("books") as batch:
            batch.alter_column("source_type", type_=sa.Enum("web", "epub", "audiobook", name="sourcetype"))


def downgrade():
    # Preserve user-created books and audio when returning to the older schema.
    op.execute("UPDATE books SET source_type = 'epub' WHERE source_type = 'audiobook'")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE books ALTER COLUMN source_type DROP DEFAULT")
        op.execute("ALTER TYPE sourcetype RENAME TO sourcetype_with_audio")
        op.execute("CREATE TYPE sourcetype AS ENUM ('web', 'epub')")
        op.execute("ALTER TABLE books ALTER COLUMN source_type TYPE sourcetype USING source_type::text::sourcetype")
        op.execute("ALTER TABLE books ALTER COLUMN source_type SET DEFAULT 'epub'")
        op.execute("DROP TYPE sourcetype_with_audio")
    else:
        with op.batch_alter_table("books") as batch:
            batch.alter_column("source_type", type_=sa.Enum("web", "epub", name="sourcetype"))
