"""Tests for the refactored CRUD modules: series, cleaning, api_keys."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app import models, schemas, crud

SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
AsyncTestingSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="function")
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncTestingSessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _create_book(db, title="Book", author="Author", series=None, **kwargs):
    return await crud.create_book(
        db,
        schemas.BookCreate(
            title=title,
            author=author,
            series=series,
            immutable_path=f"lib/immutable_{title}.epub",
            current_path=f"lib/{title}.epub",
            source_type=models.SourceType.epub,
            **kwargs,
        ),
    )


class TestBooksCrud:
    @pytest.mark.asyncio
    async def test_create_and_get_book(self, db):
        book = await _create_book(db, "Test", "Author")
        assert book.id is not None
        fetched = await crud.get_book(db, book.id)
        assert fetched.title == "Test"

    @pytest.mark.asyncio
    async def test_get_book_by_title_and_author_case_insensitive(self, db):
        await _create_book(db, "My Book", "John Doe")
        found = await crud.get_book_by_title_and_author(db, "my book", "john doe")
        assert found is not None
        assert found.title == "My Book"

    @pytest.mark.asyncio
    async def test_count_books_with_search(self, db):
        await _create_book(db, "Dragon Fire", "Alice")
        await _create_book(db, "Moonlight", "Bob")
        assert await crud.count_books(db) == 2
        assert await crud.count_books(db, q="dragon") == 1
        assert await crud.count_books(db, q="zzz") == 0

    @pytest.mark.asyncio
    async def test_touch_book_content(self, db):
        book = await _create_book(db, "Touch Test", "Author")
        old_version = book.content_version
        await crud.touch_book_content(db, book)
        assert book.content_version == old_version + 1

    @pytest.mark.asyncio
    async def test_detach_book_source(self, db):
        book = await _create_book(db, "Web Book", "Author", source_url="http://example.com/story")
        book.source_type = models.SourceType.web
        book.download_status = "complete"
        await db.commit()
        detached = await crud.detach_book_source(db, book)
        assert detached.source_url is None
        assert detached.source_type == models.SourceType.epub
        assert detached.download_status is None


class TestSeriesCrud:
    @pytest.mark.asyncio
    async def test_get_all_series(self, db):
        await _create_book(db, "Book A", "Author", series="Alpha")
        await _create_book(db, "Book B", "Author", series="Beta")
        await _create_book(db, "Book C", "Author")  # no series
        series = await crud.get_all_series(db)
        assert series == ["Alpha", "Beta"]

    @pytest.mark.asyncio
    async def test_rename_series(self, db):
        await _create_book(db, "Book A", "Author", series="Old Name")
        await _create_book(db, "Book B", "Author", series="Old Name")
        count = await crud.rename_series(db, "Old Name", "New Name")
        assert count == 2
        series = await crud.get_all_series(db)
        assert "New Name" in series
        assert "Old Name" not in series

    @pytest.mark.asyncio
    async def test_merge_series(self, db):
        await _create_book(db, "Book A", "Author", series="Source")
        await _create_book(db, "Book B", "Author", series="Target")
        count = await crud.merge_series(db, "Source", "Target")
        assert count == 1
        series = await crud.get_all_series(db)
        assert series == ["Target"]

    @pytest.mark.asyncio
    async def test_get_books_by_series_case_insensitive(self, db):
        await _create_book(db, "Book A", "Author", series="My Series")
        books = await crud.get_books_by_series(db, "my series")
        assert len(books) == 1
        assert books[0].title == "Book A"


class TestLogsCrud:
    @pytest.mark.asyncio
    async def test_create_and_get_book_log(self, db):
        book = await _create_book(db, "Logged Book", "Author")
        log = await crud.create_book_log(
            db,
            schemas.BookLogCreate(
                book_id=book.id,
                entry_type="added",
                new_chapter_count=10,
                words_added=5000,
            ),
        )
        assert log.id is not None
        assert log.entry_type == "added"

        latest = await crud.get_latest_book_log(db, book.id)
        assert latest.id == log.id

    @pytest.mark.asyncio
    async def test_count_book_logs(self, db):
        book = await _create_book(db, "Count Book", "Author")
        assert await crud.count_book_logs(db, book.id) == 0
        await crud.create_book_log(
            db, schemas.BookLogCreate(book_id=book.id, entry_type="added")
        )
        assert await crud.count_book_logs(db, book.id) == 1

    @pytest.mark.asyncio
    async def test_update_task_lifecycle(self, db):
        task = await crud.create_update_task(db, total_books=5)
        assert task.status == "running"
        assert task.completed_books == 0

        await crud.increment_update_task(db, task)
        assert task.completed_books == 1

        await crud.complete_update_task(db, task)
        assert task.status == "completed"
        assert task.completed_at is not None

    @pytest.mark.asyncio
    async def test_fail_update_task(self, db):
        task = await crud.create_update_task(db, total_books=3)
        await crud.fail_update_task(db, task)
        assert task.status == "failed"

    @pytest.mark.asyncio
    async def test_reset_stuck_update_tasks(self, db):
        task = await crud.create_update_task(db, total_books=1)
        assert task.status == "running"
        await crud.reset_stuck_update_tasks(db)
        await db.refresh(task)
        assert task.status == "failed"


class TestCleaningCrud:
    @pytest.mark.asyncio
    async def test_cleaning_config_crud(self, db):
        config = await crud.create_cleaning_config(
            db,
            schemas.CleaningConfigCreate(
                name="Test Config",
                url_pattern="example\\.com",
                content_selectors=["div.ad"],
            ),
        )
        assert config.id is not None

        configs = await crud.get_cleaning_configs(db)
        assert len(configs) == 1

        fetched = await crud.get_cleaning_config(db, config.id)
        assert fetched.name == "Test Config"

        updated = await crud.update_cleaning_config(
            db,
            config,
            schemas.CleaningConfigUpdate(name="Updated"),
        )
        assert updated.name == "Updated"

        await crud.delete_cleaning_config(db, config)
        assert await crud.get_cleaning_config(db, config.id) is None

    @pytest.mark.asyncio
    async def test_get_matching_cleaning_config(self, db):
        await crud.create_cleaning_config(
            db,
            schemas.CleaningConfigCreate(
                name="RR Config",
                url_pattern="royalroad\\.com",
            ),
        )
        match = await crud.get_matching_cleaning_config(db, "https://www.royalroad.com/fiction/123")
        assert match is not None
        assert match.name == "RR Config"

        no_match = await crud.get_matching_cleaning_config(db, "https://other.com/story")
        assert no_match is None


class TestApiKeysCrud:
    @pytest.mark.asyncio
    async def test_create_and_list_api_keys(self, db):
        from backend.app.auth import generate_reader_token

        token, prefix = generate_reader_token()
        key = await crud.create_api_key(db, "Test Key", token, prefix)
        assert key.label == "Test Key"
        assert key.token_prefix == prefix

        keys = await crud.get_api_keys(db)
        assert len(keys) == 1

    @pytest.mark.asyncio
    async def test_revoke_api_key(self, db):
        from backend.app.auth import generate_reader_token

        token, prefix = generate_reader_token()
        key = await crud.create_api_key(db, "Revoke Me", token, prefix)
        assert key.revoked_at is None

        result = await crud.revoke_api_key(db, key.id)
        assert result is True
        await db.refresh(key)
        assert key.revoked_at is not None

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_key(self, db):
        result = await crud.revoke_api_key(db, 99999)
        assert result is False
