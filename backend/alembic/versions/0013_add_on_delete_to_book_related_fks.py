"""add on-delete rules to book-related foreign keys

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-01 13:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _replace_fk(
    conn,
    *,
    table_name: str,
    constrained_columns: list[str],
    referred_table: str,
    referred_columns: list[str],
    new_name: str,
    ondelete: str | None,
) -> None:
    inspector = sa.inspect(conn)
    if not inspector.has_table(table_name) or not inspector.has_table(referred_table):
        return

    existing_fk = next(
        (
            fk
            for fk in inspector.get_foreign_keys(table_name)
            if fk["referred_table"] == referred_table and fk["constrained_columns"] == constrained_columns
        ),
        None,
    )

    existing_ondelete = (existing_fk or {}).get("options", {}).get("ondelete")
    if existing_fk and existing_ondelete == ondelete:
        return

    if existing_fk and existing_fk.get("name"):
        op.drop_constraint(existing_fk["name"], table_name, type_="foreignkey")

    op.create_foreign_key(
        new_name,
        table_name,
        referred_table,
        constrained_columns,
        referred_columns,
        ondelete=ondelete,
    )


def upgrade() -> None:
    conn = op.get_bind()

    _replace_fk(
        conn,
        table_name="book_logs",
        constrained_columns=["book_id"],
        referred_table="books",
        referred_columns=["id"],
        new_name="fk_book_logs_book_id_books",
        ondelete="CASCADE",
    )
    _replace_fk(
        conn,
        table_name="book_metadata_matches",
        constrained_columns=["book_id"],
        referred_table="books",
        referred_columns=["id"],
        new_name="fk_book_metadata_matches_book_id_books",
        ondelete="CASCADE",
    )
    _replace_fk(
        conn,
        table_name="metadata_proposals",
        constrained_columns=["book_id"],
        referred_table="books",
        referred_columns=["id"],
        new_name="fk_metadata_proposals_book_id_books",
        ondelete="CASCADE",
    )
    _replace_fk(
        conn,
        table_name="metadata_proposals",
        constrained_columns=["match_id"],
        referred_table="book_metadata_matches",
        referred_columns=["id"],
        new_name="fk_metadata_proposals_match_id_book_metadata_matches",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    conn = op.get_bind()

    _replace_fk(
        conn,
        table_name="metadata_proposals",
        constrained_columns=["match_id"],
        referred_table="book_metadata_matches",
        referred_columns=["id"],
        new_name="fk_metadata_proposals_match_id_book_metadata_matches",
        ondelete=None,
    )
    _replace_fk(
        conn,
        table_name="metadata_proposals",
        constrained_columns=["book_id"],
        referred_table="books",
        referred_columns=["id"],
        new_name="fk_metadata_proposals_book_id_books",
        ondelete=None,
    )
    _replace_fk(
        conn,
        table_name="book_metadata_matches",
        constrained_columns=["book_id"],
        referred_table="books",
        referred_columns=["id"],
        new_name="fk_book_metadata_matches_book_id_books",
        ondelete=None,
    )
    _replace_fk(
        conn,
        table_name="book_logs",
        constrained_columns=["book_id"],
        referred_table="books",
        referred_columns=["id"],
        new_name="fk_book_logs_book_id_books",
        ondelete=None,
    )
