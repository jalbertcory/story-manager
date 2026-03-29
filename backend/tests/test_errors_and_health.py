"""Tests for structured error responses and the health check endpoint."""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.main import app
from backend.app.database import Base, get_db

SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
AsyncTestingSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


async def override_get_db():
    async with AsyncTestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def db_session():
    # Save and restore the original override to avoid interfering with other test files
    original_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    if original_override is not None:
        app.dependency_overrides[get_db] = original_override
    else:
        app.dependency_overrides.pop(get_db, None)


client = TestClient(app)


class TestStructuredErrors:
    @pytest.mark.asyncio
    async def test_404_returns_structured_error(self, db_session):
        response = client.get("/api/books/99999")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert data["error"] == "not_found"
        assert "detail" in data
        assert data["status_code"] == 404

    @pytest.mark.asyncio
    async def test_400_returns_structured_error(self, db_session):
        response = client.post("/api/books/add_web_novel", json={"url": "not-a-url"})
        # Pydantic validation returns 422
        assert response.status_code in (400, 422)
        data = response.json()
        assert "detail" in data


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_healthy(self, db_session):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
