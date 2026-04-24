# Reader API

Story Manager includes a read-only reader API for e-readers and OPDS clients.

## API Keys

Create reader keys from the web UI:

1. Open `Utilities`.
2. Use the `Reader API Keys` section.
3. Create one key per device, such as `Kobo` or `Boox`.
4. Save the full token when it is shown. It is displayed only once.

## Authentication

Reader clients can authenticate with any of these options:

```http
Authorization: Bearer <token>
```

HTTP Basic auth with any username and the token as the password.

```text
?api_key=<token>
```

Use query-string credentials only for clients that cannot send headers.

## Endpoints

- `GET /reader/opds`
- `GET /reader/opds/catalog`
- `GET /reader/opds/search?q=...`
- `GET /reader/books/all`
- `GET /reader/updates?since=2026-03-14T12:00:00Z`
- `GET /reader/books/{id}`
- `GET /reader/books/{id}/download`
- `GET /reader/covers/{id}`

The `/reader/*` namespace is read-only. The existing `/api/*` routes are admin-style application routes for the web UI.
