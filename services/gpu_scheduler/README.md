# GPU Availability Controller

This sidecar starts and stops selected Docker containers according to weekly active hours. It is intended for a
Windows gaming PC that contributes Ollama, OmniVoice, or WhisperX capacity whenever the GPU is not reserved for
games. Story Manager's ordered endpoint pools automatically use another host while these containers are stopped.

## Gaming PC: first-time setup

The four services are:

| Service | Image | Port |
|---|---|---|
| Availability controller | `ghcr.io/jalbertcory/story-manager-gpu-scheduler:latest` | `8765` on localhost |
| Ollama | `ollama/ollama:latest` | `11434` |
| OmniVoice | `ghcr.io/jalbertcory/story-manager-omnivoice:latest` | `8001` |
| WhisperX | `ghcr.io/jalbertcory/story-manager-transcription:latest` | `8002` |

Install Docker Desktop, enable its WSL 2 backend, and confirm NVIDIA GPU support works. Install `git` and `make` in
the PowerShell/WSL environment where the commands will run. Then clone the project:

```powershell
git clone https://github.com/jalbertcory/story-manager.git
cd story-manager
```

Create the four services and start the controller:

```powershell
make managed-ai
```

Open <http://127.0.0.1:8765> on the gaming PC. Select the weekly hours during which AI services may run, then enable
the schedule. The controller starts in **observe-only** mode, so Ollama, OmniVoice, and WhisperX remain stopped until
the schedule is enabled or **AI on · 2 hours** is selected.

While Ollama is available, install the recommended model once:

```powershell
docker exec story-manager-ollama ollama pull qwen3.5:9b
```

Confirm the controller and model-container state:

```powershell
make gpu-services-status
```

`make managed-ai` starts the controller, creates Ollama, OmniVoice, and WhisperX if they do not exist, and asks the
controller to apply the saved policy. It does not force the model containers on outside their configured active
hours. Running it again pulls updated controller and model images, preserves every model/configuration volume, and
reapplies the saved policy.

The example Compose project includes Ollama, OmniVoice, and WhisperX. Remove any services the gaming PC should not
host.

Give the PC a DHCP reservation, allow inbound ports `11434`, `8001`, and `8002` only from the Story Manager host, and
add the gaming PC endpoints above the always-on fallbacks in **Audio & AI Configuration**.

## Managing other containers

The controller only manages containers with this exact label:

```yaml
labels:
  story-manager.gpu-scheduler.managed: "true"
```

An optional numeric label controls startup order. Shutdown happens in reverse order:

```yaml
labels:
  story-manager.gpu-scheduler.order: "10"
```

It never removes or recreates containers. A stopped service retains its container, volumes, models, and
`unless-stopped` restart behavior.

## Security boundary

The controller can talk to the Docker Engine through its socket, which grants powerful host-level Docker access.
The supplied Compose file publishes the UI only on Windows localhost. Do not change it to a LAN-wide binding unless
the network and host are appropriately protected. The API cannot select arbitrary containers; discovery and actions
are restricted to the managed label.

The controller cannot stop Docker Desktop itself because that would also stop the scheduler. Stopping the managed
model containers releases their GPU allocations while leaving Docker Desktop available to wake them later.

## macOS development

`make run-gpu-scheduler` works on Docker Desktop for macOS and is useful for testing the control panel. The normal
`make start` development path deliberately continues to run Ollama, OmniVoice, and WhisperX natively: Docker Desktop
cannot pass an Apple GPU through to Linux containers, while the native services can use Metal/MPS. Use
`make managed-ai` for the NVIDIA Windows host where the model containers should be scheduler-controlled. To test an
unpublished local controller change, use `make run-gpu-scheduler GPU_SCHEDULER_BUILD=--build`.

## Image publishing

The project-owned images are published to GitHub Container Registry only when their relevant service paths change.
Pull requests build affected images without publishing them; a merge to `main` publishes `latest` and `main` tags.
The workflows are independent, so a scheduler-only change does not rebuild OmniVoice or WhisperX. Ollama is consumed
from its official upstream image and is not republished by this project.

## Configuration

Configuration is stored in the `gpu-scheduler-data` named volume. Supported environment variables are:

| Variable | Default | Purpose |
|---|---|---|
| `SCHEDULER_TIMEZONE` | `TZ`, then `UTC` | Initial IANA timezone before the first save |
| `SCHEDULER_DATA_PATH` | `/data/config.json` | Persistent configuration path |
| `SCHEDULER_RECONCILE_SECONDS` | `15` | Seconds between desired-state checks; minimum 5 |

## Local tests

```bash
uv sync --project services/gpu_scheduler
PYTHONPATH=. uv run --project services/gpu_scheduler pytest services/gpu_scheduler/tests
```
