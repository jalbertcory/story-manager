# Local OmniVoice Adapter

This service wraps the official Apache-2.0
[`k2-fsa/OmniVoice`](https://github.com/k2-fsa/OmniVoice) 0.2.1 model in Story Manager's
`POST /generate` HTTP contract. It keeps the model loaded between sentence requests and returns MP3 bytes. It also
offers `POST /generate-batch` for accelerators where native model batching improves throughput; Story Manager falls
back to isolated sentence requests if a batch fails.

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
| `OMNIVOICE_MAX_BATCH_SIZE` | `8` | Maximum items accepted by `POST /generate-batch` |
| `OMNIVOICE_NATIVE_BATCHING` | `false` | Opt into native model batching. Keep disabled on MPS, where native batches can produce stationary mechanical noise. |
| `OMNIVOICE_NORMALIZE_TEXT` | `true` | Speak numbers, dates, and currency in words before synthesis (see [Text normalization](#text-normalization)). Set `false` to pass sentence text through unchanged. |
| `OMNIVOICE_QUALITY_ATTEMPTS` | `3` | Maximum individual generations attempted when the signal-quality gate rejects an output. |
| `OMNIVOICE_VOICE_STORE` | `$HF_HOME/voices` | Persistent enrollment samples backing reusable voice IDs. The default is inside the mapped `/models` volume in Docker. |
| `OMNIVOICE_PORT` | `8001` | Port used by the Make target |

Story Manager controls submitted batch size with `AUDIOBOOK_TTS_BATCH_SIZE` (default `4`) and length-buckets
independent clips before submission. Bucketing matters on Apple MPS because every native batch is padded to its
longest item; mixed-length batches can be slower than single inference. `AUDIOBOOK_TTS_WORKERS` defaults to `1`;
analysis and speech still run concurrently in separate pipeline lanes.

Legacy Story Manager profiles such as `[gender-female][pitch-low][speed-normal]` are translated into the official
comma-separated voice-design attributes. Official instructions such as `female, middle-aged, low pitch` are also
accepted directly. Supported OmniVoice non-verbal tags are preserved; unsupported historical tags are removed so
one bad expression tag cannot fail a full audiobook run.

## Text normalization

OmniVoice reads digits poorly on its own: in testing it dropped "million" from "2,000,000", read "15%" as
"15 fairs", and lost the cents in "$1,250.50". The adapter therefore enables OmniVoice 0.2.1's
`generate(normalize_text=True)`, which rewrites numbers, dates, times, ordinals, and percentages into words
before synthesis. Before that, a small pre-pass in `normalization.py` spells out four-digit decades ("1990s") and
dollar amounts with cents ("$5.99"), which the upstream English normalizer misreads as "nineteen hundred and ninety
seconds" and "five point nine nine dollars". Normalization applies only to sentence text. It is not applied to
voice-design enrollment text or to the stored `ref_text`, which must match the reference sample word for word.

The upstream normalizer depends on WeTextProcessing and `pynini`, and `pynini` publishes wheels only for Linux
x86_64. The Docker image and Linux x86_64 installs include it. On macOS and Linux arm64, the adapter logs a warning at
startup, reports `"normalize_text": false` from `/health`, and passes text through unchanged. Some forms are still
read imperfectly even with normalization: `24/7` and `9/11` are read as fractions, phone numbers are mangled, and
slash dates are read day-first (`4/5/1984` becomes "the fifth of April").

## Consistent voices

OmniVoice voice-design instructions describe a class of voices; they do not select one speaker. Story Manager's
adapter therefore designs one enrollment performance with `POST /voices/design`, saves its WAV file under
`OMNIVOICE_VOICE_STORE`, and returns an `omnivoice-...` ID. Later `/generate` and `/generate-batch` requests pass that
ID into OmniVoice's reusable voice-cloning prompt while retaining the original instruction as compatible style
guidance.

Story Manager provisions this ID automatically the first time a roster voice is used and saves it on both the book
and series character profiles. The roster also offers **Create Consistent Voice** / **Replace Voice Design** controls
for auditioning a sample before full-book generation. Keep the `/models` volume when replacing or upgrading the
container. Multiple OmniVoice workers must mount the same voice-store directory if they are used as fallbacks.
