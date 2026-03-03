# Agent Instructions

This document provides instructions for agents working on this project.

## Local Development Setup

For the Jules AI Agent this project uses a local PostgreSQL installation for the database. The `setupJules.sh` script was already run and automatically installed and configured PostgreSQL.
All other agents should use `make run-db` to run a pgsql container.

### Database Credentials

The following credentials are used to connect to the local PostgreSQL database:

- **Username:** `storyuser`
- **Password:** `storypass`
- **Database:** `story_manager`

You can connect to the database using the following command:

```bash
psql -h localhost -p 5432 -U storyuser -d story_manager
```

## Database Changes: Always Use Migrations

One-time database changes — creating tables, altering columns, seeding default data, fixing bad data — must go in an Alembic migration, not in application startup code.

**Do not** add seeding or fixup logic to the app lifespan / startup (e.g. `seed_default_cleaning_config()` in `main.py`). Those functions run on every boot, are hard to test in isolation, and have no history or rollback mechanism.

**Do** write a numbered migration in `backend/alembic/versions/`. Migrations run exactly once (tracked in `alembic_version`), are reversible via `downgrade()`, and are tested before any code reaches production.

### Writing migrations that handle existing data

This is a user-facing service: real users may have already created books, cleaning configs, and other records. Every migration must work correctly against an existing populated database, not just a blank one.

**Key rules:**

1. **Never assume a table is empty.** If you are seeding a default row, check whether it already exists before inserting. Use a `SELECT` first, or an `INSERT ... WHERE NOT EXISTS` / `ON CONFLICT DO NOTHING`.

2. **Never assume a table was created by a migration.** Some tables in this project were historically created by SQLAlchemy's `create_all()` at app startup rather than by a migration. Before querying such a table from a migration, check whether it exists:
   ```python
   if not sa.inspect(conn).has_table("table_name"):
       op.create_table("table_name", ...)
   ```

3. **Use SQLAlchemy table constructs, not raw `text()`, when touching typed columns.** PostgreSQL's `json`/`jsonb` columns reject plain string-bound parameters. Use `sa.table()` + `sa.column()` so SQLAlchemy handles type coercion:
   ```python
   my_table = sa.table(
       "my_table",
       sa.column("id", sa.Integer),
       sa.column("data", sa.JSON),
   )
   conn.execute(my_table.insert().values(data={"key": "value"}))
   ```

4. **Write a `downgrade()`.** It should reverse exactly what `upgrade()` did — revert data changes, drop columns/tables that were added. It is acceptable for `downgrade()` to skip dropping a table that was conditionally created (since you cannot safely know whether the table was pre-existing).

5. **Test against PostgreSQL before merging** (see Migration Testing section below). SQLite (used by unit tests) is more permissive than PostgreSQL; a migration that passes locally may still fail in the container.

### Example: seeding a default row safely

```python
def upgrade():
    conn = op.get_bind()

    # Create the table if it was not already created by an earlier mechanism
    if not sa.inspect(conn).has_table("my_configs"):
        op.create_table(
            "my_configs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False, unique=True),
            sa.Column("data", sa.JSON(), nullable=True),
        )

    my_configs = sa.table(
        "my_configs",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("data", sa.JSON),
    )

    # Only insert if the default row does not already exist
    exists = conn.execute(
        sa.select(my_configs.c.id).where(my_configs.c.name == "Default")
    ).fetchone()

    if not exists:
        conn.execute(my_configs.insert().values(name="Default", data={"key": "value"}))
```

## Migration Testing

When you create a new database migration, you need to test it properly before merging. Migrations that are merged into `main` are considered to be live in user databases, so it's important to test them against a database that is in the same state as `main`.

### Quick test against a throwaway PostgreSQL container

This approach spins up a clean Postgres instance, runs all migrations from scratch, and tears it down — no local PostgreSQL installation required.

```bash
# Start a throwaway container
docker run --name pg-migration-test \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=story_manager \
  -p 5433:5432 -d postgres:16

# Wait for it to be ready
until docker exec pg-migration-test pg_isready -U postgres; do sleep 1; done

# Run all migrations
DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5433/story_manager" \
  PYTHONPATH=. uv run alembic -c backend/alembic.ini upgrade head

# Tear down
docker rm -f pg-migration-test
```

Also test the **existing-data path**: roll back to the previous revision, insert representative existing rows, then upgrade and verify the result is correct.

```bash
# Roll back one step
DATABASE_URL="..." PYTHONPATH=. uv run alembic -c backend/alembic.ini downgrade -1

# Insert existing data that would be present on a live user's database
docker exec pg-migration-test psql -U postgres -d story_manager \
  -c "INSERT INTO my_table (...) VALUES (...);"

# Re-apply the migration and verify
DATABASE_URL="..." PYTHONPATH=. uv run alembic -c backend/alembic.ini upgrade head
docker exec pg-migration-test psql -U postgres -d story_manager \
  -c "SELECT * FROM my_table;"
```

### Test against a local database at the state of `main`

Before running tests for your migration, you should reset your local database to the state of the `main` branch. Here's how you can do that:

1.  **Commit your changes:**
    Make sure your new migration file is committed to your feature branch.

2.  **Switch to the `main` branch:**
    ```bash
    git checkout main
    git pull origin main
    ```

3.  **Upgrade your database to the head of `main`:**
    ```bash
    export PYTHONPATH=. && .venv/bin/alembic upgrade head
    ```

4.  **Switch back to your feature branch:**
    ```bash
    git checkout -
    ```

5.  **Run your tests:**
    Now that your database is at the same state as `main`, you can run your tests. The `run-backend` command will automatically apply the new migrations from your feature branch. You can then run the test suite.
    ```bash
    make test
    ```

## End-to-End (E2E) Testing

To run the Playwright end-to-end tests, you first need to ensure the backend and frontend servers are running.

1.  **Start the servers:**
    In separate terminals, run the following commands:
    ```bash
    make run-api
    make run-ui
    ```

2.  **Run the E2E tests:**
    Once the servers are running, you can execute the E2E tests with the following command:
    ```bash
    make e2e
    ```

    To run in debug mode, use:
    ```bash
    make e2e-debug
    ```
