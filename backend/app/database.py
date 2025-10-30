import os
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

# Load environment variables from .env file
load_dotenv()

# Define the database URL for a local PostgreSQL database. The database will
# run inside the same container and be available on the default port.
#
# The credentials and database name can be configured via the DATABASE_URL
# environment variable. If not set, falls back to default postgres credentials.
# Use psycopg (v3) as the async driver to avoid building the asyncpg C extension,
# which lacks Python 3.13 wheels and fails to compile. Psycopg ships wheels for
# newer Python versions, keeping installs fast and reliable.
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/story_manager")

# Create an async engine for PostgreSQL. `echo=True` can be enabled for SQL
# debugging purposes.
engine = create_async_engine(DATABASE_URL)

# Create a configured "Session" class.
# This is the factory for our database sessions.
SessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create a base class for our declarative models.
Base = declarative_base()


# Dependency to get a DB session.
# This will be used in API endpoints to get a database session.
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
