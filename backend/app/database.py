from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

# Define the database URL. For this project, we use an async SQLite driver.
# The database file will be created in the `backend` directory.
DATABASE_URL = "sqlite+aiosqlite:///../story_manager.db"

# Create an async engine. `echo=True` is useful for debugging SQL queries.
engine = create_async_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Create a configured "Session" class.
# This is the factory for our database sessions.
AsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create a base class for our declarative models.
Base = declarative_base()

# Dependency to get a DB session.
# This will be used in API endpoints to get a database session.
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
