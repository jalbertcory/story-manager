"""add durable reader audiobook publication metadata

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-21 00:00:00
"""

from __future__ import annotations

import hashlib
import posixpath

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


BOOK_COLUMNS = (
    sa.Column("audiobook_revision", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("audiobook_source_content_version", sa.Integer(), nullable=True),
    sa.Column("audiobook_text_content_version", sa.Integer(), nullable=True),
    sa.Column("audiobook_pending_content_version", sa.Integer(), nullable=True),
    sa.Column("audiobook_publication_state", sa.String(), nullable=True),
    sa.Column("audiobook_text_file_path", sa.String(), nullable=True),
    sa.Column("audiobook_text_size_bytes", sa.BigInteger(), nullable=True),
    sa.Column("audiobook_text_sha256", sa.String(length=64), nullable=True),
    sa.Column("audiobook_publication_error", sa.Text(), nullable=True),
)

CHAPTER_COLUMNS = (
    sa.Column("stable_chapter_key", sa.String(), nullable=True),
    sa.Column("source_href", sa.String(), nullable=True),
    sa.Column("source_content_hash", sa.String(length=64), nullable=True),
    sa.Column("title", sa.String(), nullable=True),
    sa.Column("spine_order", sa.Integer(), nullable=True),
    sa.Column("generation_state", sa.String(), nullable=False, server_default="pending"),
    sa.Column("audio_revision", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("reader_audio_file_path", sa.String(), nullable=True),
    sa.Column("reader_smil_file_path", sa.String(), nullable=True),
    sa.Column("audio_size_bytes", sa.BigInteger(), nullable=True),
    sa.Column("audio_sha256", sa.String(length=64), nullable=True),
    sa.Column("smil_size_bytes", sa.BigInteger(), nullable=True),
    sa.Column("smil_sha256", sa.String(length=64), nullable=True),
    sa.Column("duration_ms", sa.BigInteger(), nullable=True),
)


def _columns(conn, table_name: str) -> set[str]:
    inspector = sa.inspect(conn)
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _normalized_href(raw: str | None, chapter_number: int) -> str:
    value = (raw or f"chapter{chapter_number:04d}.xhtml").replace("\\", "/").lstrip("/")
    normalized = posixpath.normpath(value)
    return normalized.removeprefix("./")


def _stable_key(href: str) -> str:
    return f"src-{hashlib.sha256(href.encode('utf-8')).hexdigest()[:16]}"


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table("books"):
        return

    book_columns = _columns(conn, "books")
    for column in BOOK_COLUMNS:
        if column.name not in book_columns:
            op.add_column("books", column.copy())

    if not inspector.has_table("audiobook_chapters"):
        op.create_table(
            "audiobook_chapters",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
            sa.Column("chapter_number", sa.Integer(), nullable=False),
            sa.Column("content_file_name", sa.String(), nullable=True),
            sa.Column("smil_file_path", sa.String(), nullable=True),
            sa.Column("audio_file_path", sa.String(), nullable=True),
            sa.Column("needs_reassembly", sa.Boolean(), nullable=False, server_default="false"),
            *[column.copy() for column in CHAPTER_COLUMNS],
        )
        op.create_index("ix_audiobook_chapters_book_id", "audiobook_chapters", ["book_id"])
    else:
        chapter_columns = _columns(conn, "audiobook_chapters")
        for column in CHAPTER_COLUMNS:
            if column.name not in chapter_columns:
                op.add_column("audiobook_chapters", column.copy())

    books = sa.table(
        "books",
        sa.column("id", sa.Integer()),
        sa.column("content_version", sa.Integer()),
        sa.column("audiobook_enabled", sa.Boolean()),
        sa.column("audiobook_pipeline_status", sa.String()),
        sa.column("audiobook_last_error", sa.Text()),
        sa.column("audiobook_revision", sa.Integer()),
        sa.column("audiobook_source_content_version", sa.Integer()),
        sa.column("audiobook_text_content_version", sa.Integer()),
        sa.column("audiobook_publication_state", sa.String()),
        sa.column("audiobook_text_file_path", sa.String()),
        sa.column("audiobook_publication_error", sa.Text()),
    )
    chapters = sa.table(
        "audiobook_chapters",
        sa.column("id", sa.Integer()),
        sa.column("book_id", sa.Integer()),
        sa.column("chapter_number", sa.Integer()),
        sa.column("content_file_name", sa.String()),
        sa.column("audio_file_path", sa.String()),
        sa.column("smil_file_path", sa.String()),
        sa.column("stable_chapter_key", sa.String()),
        sa.column("source_href", sa.String()),
        sa.column("title", sa.String()),
        sa.column("spine_order", sa.Integer()),
        sa.column("generation_state", sa.String()),
        sa.column("audio_revision", sa.Integer()),
        sa.column("reader_audio_file_path", sa.String()),
        sa.column("reader_smil_file_path", sa.String()),
        sa.column("duration_ms", sa.BigInteger()),
    )

    durations: dict[int, int] = {}
    if sa.inspect(conn).has_table("audiobook_sentences"):
        sentences = sa.table(
            "audiobook_sentences",
            sa.column("chapter_id", sa.Integer()),
            sa.column("audio_duration_ms", sa.Integer()),
        )
        durations = {
            row.chapter_id: int(row.duration_ms or 0)
            for row in conn.execute(
                sa.select(
                    sentences.c.chapter_id,
                    sa.func.sum(sentences.c.audio_duration_ms).label("duration_ms"),
                ).group_by(sentences.c.chapter_id)
            ).fetchall()
        }

    used_keys: dict[int, set[str]] = {}
    chapter_rows = conn.execute(
        sa.select(
            chapters.c.id,
            chapters.c.book_id,
            chapters.c.chapter_number,
            chapters.c.content_file_name,
            chapters.c.audio_file_path,
            chapters.c.smil_file_path,
            chapters.c.stable_chapter_key,
        ).order_by(chapters.c.book_id, chapters.c.chapter_number)
    ).fetchall()
    chapter_counts: dict[int, tuple[int, int]] = {}
    for row in chapter_rows:
        href = _normalized_href(row.content_file_name, row.chapter_number)
        key = row.stable_chapter_key or _stable_key(href)
        keys = used_keys.setdefault(row.book_id, set())
        candidate = key
        suffix = 2
        while candidate in keys:
            candidate = f"{key}-{suffix}"
            suffix += 1
        keys.add(candidate)
        ready = bool(row.audio_file_path and row.smil_file_path)
        total, ready_count = chapter_counts.get(row.book_id, (0, 0))
        chapter_counts[row.book_id] = (total + 1, ready_count + int(ready))
        conn.execute(
            chapters.update()
            .where(chapters.c.id == row.id)
            .values(
                stable_chapter_key=candidate,
                source_href=href,
                title=f"Chapter {row.chapter_number}",
                spine_order=max(0, row.chapter_number - 1),
                generation_state="ready" if ready else "pending",
                audio_revision=1 if ready else 0,
                reader_audio_file_path=row.audio_file_path,
                reader_smil_file_path=row.smil_file_path,
                duration_ms=durations.get(row.id),
            )
        )

    for row in conn.execute(
        sa.select(
            books.c.id,
            books.c.content_version,
            books.c.audiobook_enabled,
            books.c.audiobook_pipeline_status,
            books.c.audiobook_last_error,
        )
    ).fetchall():
        if not row.audiobook_enabled:
            continue
        total, ready = chapter_counts.get(row.id, (0, 0))
        if row.audiobook_pipeline_status == "error":
            state = "error"
        elif total and ready == total and row.audiobook_pipeline_status == "complete":
            state = "complete"
        elif ready:
            state = "partial"
        else:
            state = "processing"
        content_version = row.content_version or 1
        conn.execute(
            books.update()
            .where(books.c.id == row.id)
            .values(
                audiobook_revision=1 if total else 0,
                audiobook_source_content_version=content_version,
                audiobook_text_content_version=content_version if total else None,
                audiobook_publication_state=state,
                audiobook_text_file_path=(f"library/audiobooks/{row.id}/working.epub" if total else None),
                audiobook_publication_error=row.audiobook_last_error,
            )
        )

    inspector = sa.inspect(conn)
    unique_names = {constraint.get("name") for constraint in inspector.get_unique_constraints("audiobook_chapters")}
    if "uq_audiobook_chapter_stable_key" not in unique_names:
        op.create_unique_constraint(
            "uq_audiobook_chapter_stable_key",
            "audiobook_chapters",
            ["book_id", "stable_chapter_key"],
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if inspector.has_table("audiobook_chapters"):
        unique_names = {constraint.get("name") for constraint in inspector.get_unique_constraints("audiobook_chapters")}
        if "uq_audiobook_chapter_stable_key" in unique_names:
            op.drop_constraint("uq_audiobook_chapter_stable_key", "audiobook_chapters", type_="unique")
        chapter_columns = _columns(conn, "audiobook_chapters")
        for column in reversed(CHAPTER_COLUMNS):
            if column.name in chapter_columns:
                op.drop_column("audiobook_chapters", column.name)

    if inspector.has_table("books"):
        book_columns = _columns(conn, "books")
        for column in reversed(BOOK_COLUMNS):
            if column.name in book_columns:
                op.drop_column("books", column.name)
