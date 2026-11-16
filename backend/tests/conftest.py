"""Shared backend test fixtures."""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.tests.storage_environment import TEST_LIBRARY_PATH
from backend.app.database import Base, get_db
from backend.app.main import app

SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session", autouse=True)
def isolated_test_library():
    """Every test's default file storage belongs to this temporary session."""
    return TEST_LIBRARY_PATH


@pytest.fixture(autouse=True)
def disable_unconfigured_network_metadata(mocker):
    """Unit tests opt providers in explicitly when their HTTP calls are mocked."""

    mocker.patch("backend.app.services.metadata.clients.GOOGLE_BOOKS_ALLOW_UNAUTHENTICATED", False)
    mocker.patch("backend.app.services.metadata.clients.GOOGLE_BOOKS_MIN_REQUEST_INTERVAL_SECONDS", 0)
    mocker.patch("backend.app.services.metadata.clients.AMAZON_METADATA_ENABLED", False)


@pytest.fixture(autouse=True)
def reset_admin_login_throttle():
    from backend.app.auth import admin_login_throttle

    admin_login_throttle.reset()
    yield
    admin_login_throttle.reset()


@pytest_asyncio.fixture
async def sqlite_sessionmaker():
    engine = create_async_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield sessionmaker
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session():
    """Tables for the shared engine that api_harness routes the app's database dependency to."""
    from api_harness import engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db(sqlite_sessionmaker):
    async with sqlite_sessionmaker() as session:
        yield session


@pytest_asyncio.fixture
async def app_client(sqlite_sessionmaker):
    async def override_get_db():
        async with sqlite_sessionmaker() as session:
            yield session

    original_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client

    if original_override is not None:
        app.dependency_overrides[get_db] = original_override
    else:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def isolate_solver_metrics(monkeypatch):
    """Solver timings queue in memory; never write them to a developer's real database."""
    from backend.app.services import solver_metrics

    def unavailable():
        raise RuntimeError("Tests that save solver metrics must supply a sessionmaker.")

    solver_metrics.reset_pending()
    monkeypatch.setattr(solver_metrics, "SessionLocal", unavailable)
    yield
    solver_metrics.reset_pending()
