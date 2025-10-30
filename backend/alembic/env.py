from logging.config import fileConfig
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool
from alembic import context

# Load environment variables from .env file
load_dotenv()

# Ensure the backend package is importable when Alembic runs from the project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from backend.app.models import Base  # noqa: E402

config = context.config
fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Override sqlalchemy.url with environment variable if set
database_url = os.getenv("DATABASE_URL")
if database_url:
    # Ensure we use psycopg (not psycopg2) for sync connections
    if "postgresql+psycopg://" in database_url:
        # Already using psycopg, keep it as is
        pass
    elif "postgresql://" in database_url:
        # Convert generic postgresql:// to use psycopg explicitly
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://")
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_online():
    from sqlalchemy import create_engine

    # Get the database URL from config
    db_url = config.get_main_option("sqlalchemy.url")

    # Create engine with explicit connect_args for psycopg sync mode
    connectable = create_engine(
        db_url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
