# Story Manager

Story Manager is a self-hosted library manager for EPUBs and web novels. It gives you a web UI for uploading, organizing, editing, and updating books, plus a read-only reader API for e-readers and OPDS clients.

## Features

- Manage uploaded EPUBs and tracked web novels in one library.
- Import individual human-narrated audiobooks or a complete Libation backup,
  match them to library EPUBs, and read along with synchronized text.
- Download and refresh supported web novels with FanFicFare.
- Preserve existing chapters when source sites remove older content.
- Edit book metadata, covers, chapters, cleaning configs, and series information.
- Expose read-only `/reader/*` endpoints secured by per-device API keys.

## Stack

- Backend: FastAPI, SQLAlchemy, Alembic, APScheduler
- Database: PostgreSQL
- Frontend: React, Vite, TanStack Query
- Packaging: Docker, Docker Compose
- Tooling: `uv`, `pyenv`, `nvm`, npm, pytest, Vitest, Playwright

## Quick Start

The simplest deployment path is Docker Compose:

```bash
docker compose up -d
```

The app is available at `http://localhost:8000`. Persistent data is stored under `./config`.

For more deployment details, see [docs/deployment.md](docs/deployment.md).

## Unraid

Story Manager can run as a single Unraid container. PostgreSQL is included in the image, so a separate database
container is not required. The LLM and text-to-speech services described below are optional and are only needed for
the audiobook pipeline; EPUB management, web-novel updates, the reader API, and OPDS work without them.

### Install Story Manager

In the Unraid web UI, open **Docker**, choose **Add Container**, switch to **Advanced View**, and use these settings:

| Setting | Value                                                                     |
|---|---------------------------------------------------------------------------|
| Name | `story-manager`                                                           |
| Repository | `ghcr.io/jalbertcory/story-manager:latest`                                |
| Network Type | `Bridge`                                                                  |
| WebUI | `http://[IP]:[PORT:8889]`                                                 |
| Port | Host `8889` -> Container `8000`                                           |
| Library path | `/mnt/user/appdata/story-manager/library` -> `/app/library` (read/write)  |
| Database path | `/mnt/user/appdata/story-manager/pgdata` -> `/tmp/pgdata` (read/write)    |
| FanFicFare config | `/mnt/user/appdata/story-manager/fanficfare` -> `/app/config` (read-only) |

The FanFicFare mapping is optional. If it is present, put custom settings in
`/mnt/user/appdata/story-manager/fanficfare/personal.ini`. The production image always starts one application worker
because Story Manager's scheduler and background queues run in process.

For a terminal-based installation, the equivalent command is:

```bash
mkdir -p /mnt/user/appdata/story-manager/{library,pgdata,fanficfare}

docker run -d \
  --name story-manager \
  --restart unless-stopped \
  -p 8889:8000 \
  -v /mnt/user/appdata/story-manager/library:/app/library \
  -v /mnt/user/appdata/story-manager/pgdata:/tmp/pgdata \
  -v /mnt/user/appdata/story-manager/fanficfare:/app/config:ro \
  ghcr.io/jalbertcory/story-manager:latest
```

Open `http://<UNRAID-IP>:8889` after the container finishes its first startup and database migrations. Turn on
**Auto Start** for the container after verifying it works.

For built-in password protection, add these container variables before exposing Story Manager outside a trusted
LAN:

```text
STORY_MANAGER_AUTH_MODE=password
STORY_MANAGER_ADMIN_PASSWORD=<a-long-unique-password>
STORY_MANAGER_ADMIN_SESSION_SECRET=<a-long-random-secret>
```

See [docs/reverse-proxy.md](docs/reverse-proxy.md) before making the service publicly accessible.

### Container networking for local AI

`127.0.0.1` and `localhost` inside Story Manager refer to the Story Manager container itself, not the Unraid host or
another container. When the AI services publish ports on Unraid, use the server's LAN address in **Audio Settings**:

```text
Ollama:            http://<UNRAID-IP>:11434
OmniVoice adapter: http://<UNRAID-IP>:8001
Kokoro FastAPI:    http://<UNRAID-IP>:8880
WhisperX:          http://<UNRAID-IP>:8002
```

As an alternative, put Story Manager and its AI services on the same user-defined Docker network and use their
container names, such as `http://ollama:11434`, `http://story-manager-omnivoice:8001`, or `http://kokoro:8880`.
Do not publish local AI endpoints to the internet; they are not authentication boundaries.

### Speech-to-text alignment for imported audiobooks

Imported human narration is immediately playable with estimated sentence
timing. For accurate highlighting, run the bundled WhisperX service and select
it under **Audio Settings → Speech-to-Text Alignment**:

```bash
mkdir -p /mnt/user/appdata/story-manager-transcription/models

docker run -d \
  --name story-manager-transcription \
  --restart unless-stopped \
  --gpus all \
  -p 8002:8002 \
  -v /mnt/user/appdata/story-manager-transcription/models:/models \
  ghcr.io/jalbertcory/story-manager-transcription:latest
```

Remove `--gpus all` for CPU-only inference. The image includes FFmpeg and
downloads transcription/alignment models into the mapped directory on first
startup. Configure `http://<UNRAID-IP>:8002`, model `large-v3`, and language
`en`, then click **Save & Test Transcription**. Ready imported editions expose
an **Improve Timestamps with Whisper** action.

### LLM for audiobook analysis

The LLM identifies recurring characters and assigns dialogue to speakers. The recommended local runtime is
[Ollama's official container](https://hub.docker.com/r/ollama/ollama), which is also available through Unraid
Community Apps.

Configure the Ollama container with:

| Setting | Value |
|---|---|
| Port | Host `11434` -> Container `11434` |
| Model data | `/mnt/user/appdata/ollama` -> `/root/.ollama` (read/write) |
| GPU | Optional, but strongly recommended for full books |

After starting Ollama, open its Unraid console and pull the recommended model:

```bash
ollama pull qwen3.5:9b
```

Then open **Audio Settings** in Story Manager and set:

| Setting | Value |
|---|---|
| Provider | `Ollama (local)` |
| Base URL | `http://<UNRAID-IP>:11434` |
| Model | `qwen3.5:9b` |

Click **Save & Test LLM** before processing a book.

[`qwen3.5:9b`](https://ollama.com/library/qwen3.5:9b) is the recommended starting point. Its Q4 model is about
6.6 GB and is sufficient for the schema-constrained character roster and speaker-assignment jobs. Allow roughly
10-12 GB of available system RAM or VRAM for the model, its 32K working context, and runtime overhead. It can run on
CPU, but analysis of a full book will be slow.

If speaker assignments need more accuracy and the server has substantially more memory,
[`qwen3.5:27b`](https://ollama.com/library/qwen3.5:27b) is a useful quality tier. Its Q4 model alone is about 17 GB,
so plan on at least 24 GB of available RAM or VRAM. Models below 9B may work, but are more likely to miss aliases,
recurring characters, or dialogue attribution and are not the recommended unattended setup.

For NVIDIA acceleration, install Unraid's NVIDIA driver support and pass the GPU through to the Ollama container as
described in the [official Ollama Docker instructions](https://hub.docker.com/r/ollama/ollama).

### TTS for audiobook speech

Text-to-speech is a separate service from Ollama. Story Manager supports:

- The bundled adapter for [`k2-fsa/OmniVoice`](https://github.com/k2-fsa/OmniVoice), which uses descriptive voice
  profiles and expression tags.
- OpenAI-compatible `/v1/audio/speech` servers, including
  [Kokoro FastAPI](https://github.com/remsky/Kokoro-FastAPI).
- OpenAI's speech API.
- ElevenLabs' text-to-speech API.

### Sometimes-available gaming PC

The optional [GPU Availability Controller](services/gpu_scheduler/README.md) runs Ollama, OmniVoice, and WhisperX on
a Windows gaming PC only during configured weekly active hours. Its local control panel starts and stops explicitly
labeled model containers while Story Manager's ordered endpoint pools route work to an always-on fallback.

For a first-time Windows setup, install Docker Desktop with its WSL 2 backend and NVIDIA GPU support, then clone this
repository and paste the following block into PowerShell from the repository root:

```powershell
$aiCompose = "services/gpu_scheduler/compose.windows.yaml"

docker compose -f $aiCompose pull gpu-scheduler ollama omnivoice transcription
docker compose -f $aiCompose up -d gpu-scheduler ollama omnivoice transcription
docker exec story-manager-ollama ollama pull qwen3.5:9b
docker compose -f $aiCompose ps -a

Start-Process "http://127.0.0.1:8765"
```

The four containers are the scheduler, Ollama, OmniVoice, and WhisperX. The model services start immediately for
initial setup while the scheduler is in observe-only mode. In the control panel, select the weekly hours when the GPU
may be used and enable the schedule. Enabling it gives the controller ownership of the model containers, so it may
stop them immediately when the current time is outside the selected hours. Use **AI on · 2 hours** for a temporary
override.

In Story Manager's **Audio & AI Configuration**, add the gaming PC's LAN endpoints: Ollama on port `11434`,
OmniVoice on port `8001`, and WhisperX on port `8002`. Keep these ports restricted to the trusted LAN. See the
[GPU Availability Controller guide](services/gpu_scheduler/README.md) for health checks, endpoint examples, the
`make managed-ai` alternative, and operational details.

OmniVoice remains the recommended local option when you want generated voice characteristics instead of selecting
from a fixed voice catalog. The character roster stores a provider-neutral voice profile plus an optional provider
voice ID, so changing providers does not require rebuilding character identity or speaker assignments.

#### OmniVoice

The model download is about 3.3 GB. A GPU with at least 4 GB of VRAM is a practical floor; 6-8 GB gives the runtime
more room. CUDA, Intel XPU, Apple MPS, and CPU are supported, although CPU generation is usually too slow for an
entire book. The default 16 diffusion steps favor throughput; 32 steps improve quality at the cost of speed.

Run the Story Manager OmniVoice image as a second Unraid container:

| Setting | Value |
|---|---|
| Name | `story-manager-omnivoice` |
| Repository | `ghcr.io/jalbertcory/story-manager-omnivoice:latest` |
| Network Type | `Bridge` |
| Port | Host `8001` -> Container `8001` |
| Model cache | `/mnt/user/appdata/story-manager-omnivoice/models` -> `/models` (read/write) |
| `OMNIVOICE_DEVICE` | `auto` |
| `OMNIVOICE_NUM_STEPS` | `16` |
| `OMNIVOICE_NATIVE_BATCHING` | `false` |
| `OMNIVOICE_QUALITY_ATTEMPTS` | `3` |

For an NVIDIA GPU, install Unraid's NVIDIA driver support and add `--gpus all` under **Extra Parameters**. The image
can fall back to CPU when no supported GPU is available, but whole-book generation will be much slower. The first
start downloads the model into the persistent cache and may take several minutes before the health endpoint becomes
ready. Allow about 4.4 GB in Unraid's Docker image for the unpacked CUDA-enabled container, plus about 3.3 GB in the
separately mapped model-cache directory.

The equivalent terminal command is:

```bash
mkdir -p /mnt/user/appdata/story-manager-omnivoice/models

docker run -d \
  --name story-manager-omnivoice \
  --restart unless-stopped \
  --gpus all \
  -p 8001:8001 \
  -e OMNIVOICE_DEVICE=auto \
  -e OMNIVOICE_NUM_STEPS=16 \
  -v /mnt/user/appdata/story-manager-omnivoice/models:/models \
  ghcr.io/jalbertcory/story-manager-omnivoice:latest
```

Remove `--gpus all` for CPU-only operation. Verify it from Unraid with:

```bash
curl http://<TTS-HOST-IP>:8001/health
```

In Story Manager's **Audio Settings**, choose **OmniVoice**, set **Base URL** to
`http://<UNRAID-IP>:8001`, then click **Save & Test TTS**. Keep this endpoint limited to the trusted LAN.

The adapter turns each character's descriptive profile into one persistent reference performance and saves the
returned OmniVoice voice ID on the book/series roster. All later sentences use voice cloning from that reference,
so the description no longer produces a different reader on every request. These references live in the mapped
`/models` volume; preserve that volume for the lifetime of the books or series.

#### Kokoro or another OpenAI-compatible server

Kokoro is a lightweight alternative with a fixed catalog of voices and works well on CPU for many home servers.
Run the Kokoro FastAPI project's CPU image as another Unraid container:

| Setting | Value |
|---|---|
| Name | `kokoro` |
| Repository | `ghcr.io/remsky/kokoro-fastapi-cpu:latest` |
| Network Type | `Bridge` |
| Port | Host `8880` -> Container `8880` |

The equivalent terminal command is:

```bash
docker run -d \
  --name kokoro \
  --restart unless-stopped \
  -p 8880:8880 \
  ghcr.io/remsky/kokoro-fastapi-cpu:latest
```

In **Audio Settings**, click **Use Local Kokoro**, replace `127.0.0.1` with the Unraid server IP when the containers
use bridge networking, and click **Save & Test TTS**. The preset uses model `kokoro` and voice `af_heart`. Other
OpenAI-compatible servers work when they accept `model`, `voice`, `input`, `response_format`, and `speed` at
`POST /v1/audio/speech`.

For a hosted provider, choose **OpenAI** or **ElevenLabs**, enter its API key, model, and default voice ID, then test
the connection. A character's **Provider Voice ID** overrides that default. Descriptive voice profiles are passed as
instructions only when the selected API/model supports them; fixed-voice APIs otherwise use the voice ID and speed.

If you only want to test the audiobook workflow without downloading AI models, select **Deterministic local
harness**. That mode creates a single narrator and silent timed MP3 placeholders; it validates the pipeline but
does not generate usable speech.

## Local Development

Install the project runtimes:

```bash
pyenv install
nvm install
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
cd frontend && npm ci && cd ..
```

Start every local service with one command:

```bash
make start
```

The command starts only missing services: PostgreSQL, Ollama, the API, the UI,
OmniVoice, and WhisperX. It waits for health checks, leaves healthy existing
processes alone, and runs detached services with logs under `.run/logs/`.
Check their current state at any time with `make services-status`.

The development UI runs at `http://localhost:5173`; the API runs at
`http://localhost:8000`. The first OmniVoice and WhisperX setups can take
several minutes. WhisperX stores downloaded models under
`.run/models/whisperx`. If the recommended Ollama model is missing, install it
with `make pull-ollama-model`.

Useful commands:

```bash
make migrate
make run-omnivoice
make run-transcription
make test
make test-migrations
make e2e
```

`make run-omnivoice` installs and runs the optional official local OmniVoice adapter for real audiobook speech.
See [services/omnivoice/README.md](services/omnivoice/README.md) for hardware notes and configuration.

`make run-transcription` installs and runs the local WhisperX word-timestamp
service. See
[services/transcription/README.md](services/transcription/README.md) for model
and hardware configuration.

For setup notes and testing details, see [docs/development.md](docs/development.md).

## Reader API

Story Manager includes a read-only API for e-readers and OPDS clients. Create one reader key per device from `Utilities` -> `Reader API Keys` in the web UI.

See [docs/reader-api.md](docs/reader-api.md) for endpoint and authentication details.

## Security

The `/reader/*` routes are read-only and use per-device API keys. The admin web UI and `/api/*` routes can use built-in password auth by setting `STORY_MANAGER_ADMIN_PASSWORD`.

If you already protect the app with a reverse proxy or Cloudflare Access, set `STORY_MANAGER_AUTH_MODE=disabled` and let that outer layer own admin authentication.

See [docs/reverse-proxy.md](docs/reverse-proxy.md) before exposing anything publicly.
