"""initial tables

Revision ID: 0001_initial
Revises:
Create Date: 2024-01-01 00:00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    source_type = sa.Enum('web', 'epub', name='sourcetype')
    source_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'books',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(), index=True),
        sa.Column('author', sa.String(), index=True),
        sa.Column('series', sa.String(), nullable=True),
        sa.Column('source_url', sa.String(), nullable=True, unique=True),
        sa.Column('source_type', source_type, nullable=False, server_default='epub'),
        sa.Column('epub_path', sa.String(), nullable=False, unique=True),
        sa.Column('cover_path', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'book_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('book_id', sa.Integer(), sa.ForeignKey('books.id'), nullable=False),
        sa.Column('entry_type', sa.String(), nullable=False),
        sa.Column('previous_chapter_count', sa.Integer(), nullable=True),
        sa.Column('new_chapter_count', sa.Integer(), nullable=True),
        sa.Column('words_added', sa.Integer(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
    )

    op.create_table(
        'update_tasks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('total_books', sa.Integer(), nullable=False),
        sa.Column('completed_books', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(), nullable=False, server_default=sa.text("'running'")),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('update_tasks')
    op.drop_table('book_logs')
    op.drop_table('books')
    sa.Enum(name='sourcetype').drop(op.get_bind(), checkfirst=True)
