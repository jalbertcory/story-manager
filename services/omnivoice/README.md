# Local OmniVoice Adapter

This service wraps the official Apache-2.0
[`k2-fsa/OmniVoice`](https://github.com/k2-fsa/OmniVoice) 0.2.0 model in Story Manager's
`POST /generate` HTTP contract. It keeps the model loaded between sentence requests and returns MP3 bytes.

## Run

From the repository root:

```bash
make run-omnivoice
```

The service requires `ffmpeg` for MP3 encoding (`brew install ffmpeg` on macOS).
The first run installs an isolated environment and downloads about 3.3 GB of public model weights to the standard
Hugging Face cache. The adapter auto-selects CUDA, XPU, Apple MPS, or CPU in that order. On Apple Silicon it enables
PyTorch's MPS fallback because the upstream audio tokenizer intentionally runs on CPU.

Verify readiness:

```bash
curl http://127.0.0.1:8001/health
```

In Story Manager, open **Audio Settings**, click **Use Local OmniVoice**, and save. The deterministic `stub`
LLM provider can remain selected; it will handle roster/diarization locally while this service produces real speech.

## Docker

The published `linux/amd64` image supports NVIDIA CUDA or CPU inference. The unpacked image is about 4.4 GB. Model
weights are downloaded on first start, so mount `/models` to persistent storage instead of storing another roughly
3.3 GB inside the container layer:

```bash
docker run -d \
  --name story-manager-omnivoice \
  --restart unless-stopped \
  --gpus all \
  -p 8001:8001 \
  -e OMNIVOICE_DEVICE=auto \
  -e OMNIVOICE_NUM_STEPS=16 \
  -v /path/to/omnivoice-models:/models \
  ghcr.io/jalbertcory/story-manager-omnivoice:latest
```

Remove `--gpus all` for CPU-only inference. The container reports healthy only after the model is loaded:

```bash
curl http://127.0.0.1:8001/health
```

The image is rebuilt and published only when files under `services/omnivoice/` or its image workflow change.

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `OMNIVOICE_MODEL` | `k2-fsa/OmniVoice` | Hugging Face model ID or local checkpoint |
| `OMNIVOICE_DEVICE` | `auto` | Force `mps`, `cuda`, `xpu`, or `cpu` |
| `OMNIVOICE_NUM_STEPS` | `16` | Diffusion steps; use `32` for higher quality/slower output |
| `OMNIVOICE_MP3_BITRATE` | `96k` | Returned MP3 bitrate |
| `OMNIVOICE_PORT` | `8001` | Port used by the Make target |

Legacy Story Manager profiles such as `[gender-female][pitch-low][speed-normal]` are translated into the official
comma-separated voice-design attributes. Official instructions such as `female, middle-aged, low pitch` are also
accepted directly. Supported OmniVoice non-verbal tags are preserved; unsupported historical tags are removed so
one bad expression tag cannot fail a full audiobook run.
