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

## Migration Testing

When you create a new database migration, you need to test it properly before merging. Migrations that are merged into `main` are considered to be live in user databases, so it's important to test them against a database that is in the same state as `main`.

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
