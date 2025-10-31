# Agent Instructions

This document provides instructions for agents working on this project.

## Local Development Setup

This project uses a local PostgreSQL installation for the database. The `setup.sh` script will automatically install and configure PostgreSQL on your local machine.

### Database Credentials

The following credentials are used to connect to the local PostgreSQL database:

- **Username:** `storyuser`
- **Password:** `storypass`
- **Database:** `story_manager`

You can connect to the database using the following command:

```bash
psql -h localhost -p 5432 -U storyuser -d story_manager
```
