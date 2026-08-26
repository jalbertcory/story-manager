# Qwen3-TTS MLX Adapter

This Apple-Silicon runtime implements the same Story Manager Qwen3-TTS HTTP contract using MLX-Audio. It reuses the
durable `qwen3-...` voice store and the shared signal/WavLM quality checks. The default clone and CustomVoice models
are the 6-bit 1.7B MLX conversions. The larger clone model is the default because it preserves enrollment-speaker
identity substantially better across long-form lines than the 0.6B variant.

`make start` selects this runtime automatically on arm64 macOS. Linux, CUDA, and CPU deployments continue to use the
PyTorch adapter in `services/qwen3_tts`. Run only this worker with:

```bash
make run-qwen3-tts-mlx
```

Override the models with `QWEN3_MLX_CLONE_MODEL` and `QWEN3_MLX_CUSTOM_MODEL`. Stored clone and preset voices are
supported. Automatic preset fallbacks are persisted as clones so a generated book does not repeatedly swap between
the clone and CustomVoice models. LoRA adapters remain a PyTorch-only feature.
