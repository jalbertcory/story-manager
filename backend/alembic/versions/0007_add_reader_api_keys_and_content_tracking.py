"""add reader api keys and content tracking

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("books"):
        op.add_column("books", sa.Column("content_updated_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column("books", sa.Column("content_version", sa.Integer(), nullable=True))

        books = sa.table(
            "books",
            sa.column("id", sa.Integer),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
            sa.column("content_updated_at", sa.DateTime(timezone=True)),
            sa.column("content_version", sa.Integer),
        )
        conn.execute(
            books.update().values(
                content_updated_at=sa.func.coalesce(books.c.updated_at, books.c.created_at, sa.func.now()),
                content_version=1,
            )
        )
        op.alter_column("books", "content_updated_at", nullable=False, server_default=sa.func.now())
        op.alter_column("books", "content_version", nullable=False, server_default="1")

    if not inspector.has_table("api_keys"):
        op.create_table(
            "api_keys",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("token_prefix", sa.String(), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("token_prefix"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index(op.f("ix_api_keys_id"), "api_keys", ["id"], unique=False)
        op.create_index(op.f("ix_api_keys_token_prefix"), "api_keys", ["token_prefix"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("api_keys"):
        op.drop_index(op.f("ix_api_keys_token_prefix"), table_name="api_keys")
        op.drop_index(op.f("ix_api_keys_id"), table_name="api_keys")
        op.drop_table("api_keys")

    if inspector.has_table("books"):
        op.drop_column("books", "content_version")
        op.drop_column("books", "content_updated_at")
