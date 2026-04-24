# Deployment

Docker Compose is the recommended deployment path.

```bash
docker compose up -d
```

The production container serves the built frontend and API from `http://localhost:8000`.

## Data Persistence

The default `docker-compose.yml` stores persistent data under `./config`:

- `config/library`: uploaded EPUBs and downloaded web novels
- `config/fanficfare`: optional FanFicFare user configuration
- `config/pgdata`: PostgreSQL data

The production image runs PostgreSQL inside the app container for simple self-hosting. If you split PostgreSQL into a separate service, set `DATABASE_URL` for the app container.

## Admin Authentication

By default, Story Manager preserves the historical local-network behavior: if no admin password is configured, the admin UI and `/api/*` routes do not require built-in login.

To enable built-in admin password auth, set:

```bash
STORY_MANAGER_AUTH_MODE=password
STORY_MANAGER_ADMIN_PASSWORD=change-me
```

The app stores a signed, HTTP-only session cookie after login. To keep sessions valid across container restarts without using the password as the signing key, also set:

```bash
STORY_MANAGER_ADMIN_SESSION_SECRET=long-random-value
```

If the app is already protected by a reverse proxy, Tailscale, Authelia, OAuth2 Proxy, or Cloudflare Access, disable built-in auth explicitly:

```bash
STORY_MANAGER_AUTH_MODE=disabled
```

## FanFicFare Overrides

Story Manager uses FanFicFare's EPUB update mode for tracked web novels. Daily checks can reuse the existing immutable EPUB instead of fetching every chapter again.

To customize FanFicFare behavior, create:

```text
config/fanficfare/personal.ini
```

Story Manager loads configs in this order:

1. Built-in `backend/app/personal.ini`
2. Optional mounted `config/fanficfare/personal.ini`

Later FanFicFare configs override earlier values. To use a different path, set `FFF_USER_CONFIG_PATH`.

## Reverse Proxy Hosts

If you access the Vite development UI through a reverse proxy or custom hostname, set `VITE_ALLOWED_HOSTS`:

```bash
VITE_ALLOWED_HOSTS=story-reader.example.com make run-ui
```

The production container serves static frontend assets through FastAPI and does not need Vite host allow-listing.

## Unraid

The provided `docker-compose.yml` is compatible with Unraid's Docker Compose Manager.

1. Copy `docker-compose.yml` to a directory such as `/mnt/user/appdata/story-manager`.
2. Start the stack from that directory with `docker compose up -d`.
3. Open `http://<UNRAID_HOST>:8000`.

Relative volume paths create `config` inside the directory where the compose file lives.
