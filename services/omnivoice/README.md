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

In Story Manager, open **Audio Settings**, click **Use Local OmniVoice Adapter**, and save. The deterministic `stub`
LLM provider can remain selected; it will handle roster/diarization locally while this service produces real speech.

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `OMNIVOICE_MODEL` | `k2-fsa/OmniVoice` | Hugging Face model ID or local checkpoint |
| `OMNIVOICE_DEVICE` | `auto` | Force `mps`, `cuda`, `xpu`, or `cpu` |
| `OMNIVOICE_NUM_STEPS` | `16` | Diffusion steps; use `32` for higher quality/slower output |
| `OMNIVOICE_MP3_BITRATE` | `96k` | Returned MP3 bitrate |
| `OMNIVOICE_PORT` | `8001` | Port used by the Make target |
| `OMNIVOICE_VOICE_ANCHOR_TEXT` | Built-in neutral calibration sentence | Text used to create each stable character voice anchor |

Legacy Story Manager profiles such as `[gender-female][pitch-low][speed-normal]` are translated into the official
comma-separated voice-design attributes. Official instructions such as `female, middle-aged, low pitch` are also
accepted directly. Supported OmniVoice non-verbal tags are preserved; unsupported historical tags are removed so
one bad expression tag cannot fail a full audiobook run.

When `voice_id` is included in a generation request, the adapter deterministically seeds a one-time voice-design
sample for that identity, converts it into OmniVoice's reusable voice-clone prompt, and caches it in memory. All
subsequent lines for that identity use the same anchor and deterministic position selection. Story Manager derives
the identity from the shared series character when available, so a recurring character retains the same voice in
sibling books. Restarting the adapter recreates the same seeded anchor on first use.
