# Local Qwen3-TTS Adapter

This optional service exposes Qwen3-TTS through Story Manager's local TTS contract. It supports:

- Stable built-in speakers with IDs such as `preset:Ryan` and `preset:Aiden`.
- Designed voices saved as durable `qwen3-...` reference clips and reused through voice cloning.
- Cross-cast WavLM separation checks that reject enrollment voices which sound too much like an existing character.
- Built-in presets that can be rendered once and persisted as clone references, keeping long-form synthesis on one model.
- Existing PEFT LoRA adapters addressed as `lora:<directory-name>`.
- Per-character deterministic seeds and WavLM speaker-similarity rejection/retry.

`make start` manages this worker with the rest of the local stack. To run only this service, use
`make run-qwen3-tts`, then add a `Qwen3-TTS` endpoint at
`http://127.0.0.1:8003`. Model variants load lazily and are swapped to limit accelerator memory use.

On Apple Silicon, `make start` automatically selects the faster MLX runtime in `services/qwen3_tts_mlx`; this
PyTorch runtime remains the CUDA, CPU, and LoRA implementation.

The clone worker defaults to `Qwen/Qwen3-TTS-12Hz-1.7B-Base` and automatically selects CUDA, Apple MPS, or CPU,
in that order. Override the model with `QWEN3_CLONE_MODEL` or the device with `QWEN3_TTS_DEVICE`. Compatible
same-character requests use Qwen's native list API so stable long-form blocks can run as one accelerator batch.

LoRA adapters live under `QWEN3_LORA_ROOT`. Each adapter directory must contain PEFT adapter files and a
`voice.json` file:

```json
{
  "ref_audio": "reference.wav",
  "ref_text": "The exact transcript of reference.wav."
}
```

The reference path must remain inside the adapter directory. Assign `lora:adapter-directory` as the character's
Provider Voice ID. For built-in voices, assign `preset:Ryan`, `preset:Aiden`, or another Qwen3 CustomVoice speaker.
Automatic roster provisioning materializes a compatible preset as a durable `qwen3-...` clone only when free-form
voice design cannot find another sufficiently distinct identity.

The first similarity-checked clone downloads `microsoft/wavlm-base-plus-sv`; preserve the Hugging Face cache along
with the Qwen model and voice-store directories.
