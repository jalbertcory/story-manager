# GPU Availability Controller

This sidecar starts and stops selected Docker containers according to weekly active hours. It is intended for a
Windows gaming PC that contributes Ollama, OmniVoice, Qwen3-TTS, or WhisperX capacity whenever the GPU is not reserved for
games. Story Manager's ordered endpoint pools automatically use another host while these containers are stopped.

## Gaming PC: first-time setup

The five services are:

| Service | Image | Port |
|---|---|---|
| Availability controller | `ghcr.io/jalbertcory/story-manager-gpu-scheduler:latest` | `8765` on localhost |
| Ollama | `ollama/ollama:latest` | `11434` |
| OmniVoice | `ghcr.io/jalbertcory/story-manager-omnivoice:latest` | `8001` |
| Qwen3-TTS | `ghcr.io/jalbertcory/story-manager-qwen3-tts:latest` | `8003` |
| WhisperX | `ghcr.io/jalbertcory/story-manager-transcription:latest` | `8002` |

Install Docker Desktop, enable its WSL 2 backend, and confirm NVIDIA GPU support works. Install Git, then clone the
project:

```powershell
git clone https://github.com/jalbertcory/story-manager.git
cd story-manager
```

From the repository root, paste this entire block into PowerShell. It downloads and starts all five containers,
installs the recommended Ollama model, prints their state, and opens the scheduler UI:

```powershell
$aiCompose = "services/gpu_scheduler/compose.windows.yaml"

docker compose -f $aiCompose pull gpu-scheduler ollama omnivoice qwen3-tts transcription
docker compose -f $aiCompose up -d gpu-scheduler ollama omnivoice qwen3-tts transcription
docker exec story-manager-ollama ollama pull qwen3.5:9b
docker compose -f $aiCompose ps -a

Start-Process "http://127.0.0.1:8765"
```

The first starts of OmniVoice, Qwen3-TTS, and WhisperX download model weights and can take several minutes. Their containers report
healthy only after those models finish loading.

In <http://127.0.0.1:8765>, select the weekly hours during which AI services may run, then enable the schedule. The
controller starts in **observe-only** mode, so it does not change the model containers started by the setup block
until scheduling is enabled. Once enabled, it reconciles them to the saved hours and may stop them immediately when
the current time is outside the selected window. Select **AI on · 2 hours** when a temporary availability override is
needed.

Confirm the controller and model-container state at any time:

```powershell
$aiCompose = "services/gpu_scheduler/compose.windows.yaml"
docker compose -f $aiCompose ps -a

curl.exe --fail http://127.0.0.1:8765/health
curl.exe --fail http://127.0.0.1:11434/api/tags
curl.exe --fail http://127.0.0.1:8001/health
curl.exe --fail http://127.0.0.1:8003/health
curl.exe --fail http://127.0.0.1:8002/health
```

If the Story Manager application runs on another computer, give the gaming PC a DHCP reservation and add these URLs
under **Audio & AI Configuration**:

| Capability | Gaming PC endpoint | Recommended model |
|---|---|---|
| LLM | `http://<GAMING-PC-IP>:11434` | `qwen3.5:9b` |
| TTS | `http://<GAMING-PC-IP>:8001` | OmniVoice |
| TTS | `http://<GAMING-PC-IP>:8003` | Qwen3-TTS |
| Speech-to-text | `http://<GAMING-PC-IP>:8002` | `large-v3` with language `en` |

Allow inbound ports `11434`, `8001`, `8002`, and `8003` only from the Story Manager host. The scheduler UI remains bound to
gaming-PC localhost and should not be exposed to the LAN.

### Make alternative

In a PowerShell, WSL, or Unix-like environment that has Make installed, the equivalent schedule-respecting setup is:

```bash
make managed-ai
make gpu-services-status
```

`make managed-ai` starts the controller, creates Ollama, OmniVoice, Qwen3-TTS, and WhisperX if they do not exist, and asks the
controller to apply the saved policy. It does not force the model containers on outside their configured active
hours. Running it again pulls updated controller and model images, preserves every model/configuration volume, and
reapplies the saved policy.

When `make managed-ai` creates Ollama for the first time, enable the schedule or select **AI on · 2 hours**, wait for
Ollama to start, and install the recommended model once:

```powershell
docker exec story-manager-ollama ollama pull qwen3.5:9b
```

The example Compose project includes Ollama, OmniVoice, Qwen3-TTS, and WhisperX. Remove any services the gaming PC should not
host.

Add the gaming PC endpoints above the always-on fallbacks in **Audio & AI Configuration** when endpoint pools are in
use.

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
`make start` development path deliberately continues to run Ollama, OmniVoice, Qwen3-TTS, and WhisperX natively: Docker Desktop
cannot pass an Apple GPU through to Linux containers, while the native services can use Metal/MPS. Use
`make managed-ai` for the NVIDIA Windows host where the model containers should be scheduler-controlled. To test an
unpublished local controller change, use `make run-gpu-scheduler GPU_SCHEDULER_BUILD=--build`.

## Image publishing

The project-owned images are published to GitHub Container Registry only when their relevant service paths change.
Pull requests build affected images without publishing them; a merge to `main` publishes `latest` and `main` tags.
The workflows are independent, so a scheduler-only change does not rebuild OmniVoice, Qwen3-TTS, or WhisperX. Ollama is consumed
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
