# Story Manager

Story Manager is a self-hosted library manager for EPUBs, web novels, and audiobooks.
Upload, organize, and edit your books in a web UI, then access them from e-readers and OPDS clients.

## Features

- Manage EPUBs and automatically refresh supported web novels with FanFicFare.
- Import audiobooks or Libation backups, and attach matching EPUBs for synchronized reading.
- Edit metadata, covers, chapters, cleaning rules, and series; enrich book details from online sources.
- Generate audiobooks with optional AI and text-to-speech services.
- Connect reader devices through a read-only API with per-device keys.

## Quick start

With Docker and Docker Compose installed, run from the repository root:

```bash
docker compose up -d
```

Open [localhost:8000](http://localhost:8000). The container includes PostgreSQL and stores
persistent data under `./config`.

See [Deployment](docs/deployment.md) for configuration and backups, or
[Unraid setup](docs/unraid.md) for Unraid installation.
Before exposing the app publicly, configure [authentication and a reverse proxy](docs/reverse-proxy.md).

## Development

Follow the [development guide](docs/development.md) to install dependencies, start local services,
and run tests. After setup, `make start` launches the services; the UI runs at
[localhost:5173](http://localhost:5173) and the API at [localhost:8000](http://localhost:8000).

## Documentation

- [Audiobooks](docs/AUDIOBOOK_PIPELINE.md): imports, adding EPUBs, text alignment, and AI narration.
- [Metadata matching](docs/metadata-matching.md): providers, automatic matching, and reviewing uncertain results.
- [Reader API](docs/reader-api.md): device keys, authentication, and endpoints.
- [AI service setup](docs/unraid.md#container-networking-for-local-ai): Ollama, transcription, and speech providers.
- [GPU Availability Controller](services/gpu_scheduler/README.md): schedule AI services on a gaming PC.
