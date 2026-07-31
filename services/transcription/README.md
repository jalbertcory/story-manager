# Local WhisperX Transcription Service

This service wraps [`m-bain/whisperX`](https://github.com/m-bain/whisperX) in
Story Manager's timestamped transcription contract. WhisperX uses
faster-whisper, voice activity detection, and a language-specific alignment
model to return forced-aligned word timestamps.

## Docker

The published `linux/amd64` image contains CUDA 12.8, cuDNN, and FFmpeg. It
supports NVIDIA GPU inference and CPU fallback. Model weights download into
`/models` on first startup and should be kept on persistent storage:

```bash
docker run -d \
  --name story-manager-transcription \
  --restart unless-stopped \
  --gpus all \
  -p 8002:8002 \
  -v /path/to/whisper-models:/models \
  ghcr.io/jalbertcory/story-manager-transcription:latest
```

Remove `--gpus all` for CPU-only inference. `large-v3` gives the best default
English accuracy but is slow on CPU; use `medium` or `small` when throughput is
more important.

Build the same production image locally with:

```bash
make build-transcription-image
```

The image is intentionally `linux/amd64`: WhisperX's current TorchCodec
dependency does not publish a Linux ARM64 wheel, and the CUDA deployment target
is an x86_64 NVIDIA host. On Apple Silicon, use `make run-transcription` for
native CPU development instead of emulating this GPU image.

Verify readiness:

```bash
curl http://127.0.0.1:8002/health
```

Then select **WhisperX service** under **Audio Settings → Speech-to-Text
Alignment** in Story Manager. When containers communicate across bridge
networks, configure the Unraid host LAN address or put both containers on the
same user-defined network.

## Local Development

FFmpeg must be installed on the host. From the repository root:

```bash
make run-transcription
```

WhisperX supports macOS through CPU inference. The first setup is large because
it installs PyTorch and downloads the selected transcription and alignment
models.

## HTTP Contract

`POST /transcribe` accepts multipart audio:

```text
file: chapter.flac
model: large-v3
language: en
```

It returns:

```json
{
  "language": "en",
  "duration": 120.5,
  "words": [
    {"word": "Hello", "start": 0.42, "end": 0.71, "score": 0.98}
  ]
}
```

Set `TRANSCRIPTION_API_KEY` to require
`Authorization: Bearer <value>` on transcription requests. The health endpoint
does not expose audio or credentials and remains available to container health
checks.

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `WHISPER_MODEL` | `large-v3` | faster-whisper model loaded at startup |
| `WHISPER_LANGUAGE` | unset | Optional language whose ASR tokenizer and aligner are preloaded |
| `WHISPER_DEVICE` | `auto` | `cuda` when available, otherwise `cpu` |
| `WHISPER_COMPUTE_TYPE` | `auto` | `float16` on CUDA, otherwise `int8` |
| `WHISPER_BATCH_SIZE` | `4` | Reduce when GPU memory is limited |
| `WHISPER_MODEL_CACHE` | `/models` | Persistent model directory |
| `TRANSCRIPTION_API_KEY` | unset | Optional bearer token |
| `TRANSCRIPTION_MAX_UPLOAD_BYTES` | `2147483648` | Maximum chapter clip size |
