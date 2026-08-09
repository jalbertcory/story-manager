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

Story Manager keeps a single-container deployment by default: the API, scheduler, and processing workers start in
the same application process. Processing ownership lives in PostgreSQL rather than process memory, so an interrupted
job is reclaimed after its lease expires and multiple application processes can claim different jobs safely.

Each kind of constrained work has its own concurrency setting. All values default to `1`:

| Variable | Work controlled |
|---|---|
| `PROCESSING_CPU_CONCURRENCY` | EPUB cleaning, audiobook import, and chapter matching |
| `PROCESSING_MAINTENANCE_CONCURRENCY` | Web imports, refreshes, covers, and scheduled maintenance |
| `PROCESSING_LLM_CONCURRENCY` | Metadata and AI audiobook analysis jobs |
| `PROCESSING_TTS_CONCURRENCY` | Speech and chapter-preview generation |
| `PROCESSING_TRANSCRIPTION_CONCURRENCY` | Human-audiobook timestamp alignment |

Operational tuning is also available through `PROCESSING_LEASE_SECONDS` (default `60`),
`PROCESSING_HEARTBEAT_SECONDS` (default `15`), `PROCESSING_POLL_SECONDS` (default `1`), and
`PROCESSING_RETRY_BACKOFF_SECONDS` (default `5`). A failed job is attempted at most three times with exponential
backoff. User-triggered retry resets that attempt budget. Cancellation is immediate for queued jobs and cooperative
at heartbeat/progress boundaries for running jobs.

Every job type has one resource lane and a stable deduplication key for its target. PostgreSQL rejects a second
queued or running job with that key, while terminal history is retained. Handlers resume from persisted book,
metadata, and audiobook state, so a worker can safely reclaim an expired lease instead of depending on an in-memory
queue notification. Claims use row locks with `SKIP LOCKED`; only the current lease owner may heartbeat or finish a
job.

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

Admin cookies automatically use the `Secure` flag when the request is HTTPS. Set `STORY_MANAGER_ADMIN_COOKIE_SECURE=true` to require secure cookies explicitly, or `false` only for a trusted HTTP-only local deployment.

If the app is already protected by a reverse proxy, Tailscale, Authelia, OAuth2 Proxy, or Cloudflare Access, disable built-in auth explicitly:

```bash
STORY_MANAGER_AUTH_MODE=disabled
```

Invalid authentication modes and password mode without a password stop the application at startup instead of disabling protection.

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

Remote cover downloads reject loopback, private, link-local, and otherwise non-public destinations. A trusted private-network deployment can opt in to private cover URLs with `STORY_MANAGER_ALLOW_PRIVATE_COVER_URLS=true`.

## Reverse Proxy Hosts

If you access the Vite development UI through a reverse proxy or custom hostname, set `VITE_ALLOWED_HOSTS`:

```bash
VITE_ALLOWED_HOSTS=story-reader.example.com make run-ui
```

The production container serves static frontend assets through FastAPI and does not need Vite host allow-listing.

## Unraid

Use the prebuilt `ghcr.io/jalbertcory/story-manager:latest` image from Unraid's **Add Container** screen. The
[Unraid guide in the README](../README.md#unraid) lists the required port and persistent path mappings, optional
authentication variables, and the supported Ollama, OmniVoice, Kokoro, OpenAI, and ElevenLabs configuration for
audiobook generation.
