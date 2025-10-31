# Agent Instructions

This document provides instructions for agents working on this project.

## Local Development Setup

For the Jules AI Agent this project uses a local PostgreSQL installation for the database. The `setup.sh` script was already run and automatically installed and configured PostgreSQL.
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
