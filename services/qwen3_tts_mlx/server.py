"""Apple-Silicon MLX runtime behind the shared Qwen3-TTS HTTP contract."""

from __future__ import annotations

import gc
import logging
import os
from pathlib import Path
import threading
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mlx_audio.tts.models.qwen3_tts.qwen3_tts import Model
    from mlx_audio.tts.models.base import GenerationResult

import mlx.core as mx
from mlx_audio.tts.utils import load_model
import numpy as np

from services.omnivoice.audio_quality import validate_generated_audio
from services.qwen3_tts import server as api
from services.qwen3_tts.voice_store import StoredVoice, VoiceStore
from services.voice_roster import SpeakerCheck

logger = logging.getLogger(__name__)
CLONE_MODEL = os.getenv("QWEN3_MLX_CLONE_MODEL", "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-6bit")
CUSTOM_MODEL = os.getenv("QWEN3_MLX_CUSTOM_MODEL", "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit")
DESIGN_MODEL = os.getenv("QWEN3_MLX_DESIGN_MODEL", "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16")


class MLXQwenRuntime:
    """Qwen3-TTS voice cloning optimized for Apple Silicon through MLX."""

    def __init__(self) -> None:
        self.device = "mlx"
        self._model_kind: str | None = None
        self._model: Model | None = None
        self._adapter_name: str | None = None
        self._lock = threading.RLock()
        self._voices = VoiceStore(api.VOICE_STORE_PATH)
        self._speaker_guard = api.speaker_guard(self._reference_path, self._generate_once)

    def load(self) -> None:
        logger.info("Qwen3-TTS MLX adapter ready; models will load lazily.")

    def _load(self, kind: str) -> Model:
        if self._model is not None and self._model_kind == kind:
            return self._model
        self._model = None
        gc.collect()
        mx.clear_cache()
        model_id = {"clone": CLONE_MODEL, "custom": CUSTOM_MODEL, "design": DESIGN_MODEL}[kind]
        logger.info("Loading %s for Qwen3-TTS MLX %s generation.", model_id, kind)
        self._model = load_model(model_id)
        self._model_kind = kind
        return self._model

    def _reference(self, voice_id: str) -> tuple[Path, str]:
        if voice_id.startswith("lora:"):
            raise ValueError("LoRA voices require the PyTorch Qwen3-TTS worker; MLX supports stored clones and presets.")
        stored = self._voices.get(voice_id)
        return self._voices.sample_path_unchecked(stored), stored.ref_text

    def _reference_path(self, voice_id: str) -> Path | None:
        if voice_id.startswith("preset:"):
            return None
        return self._reference(voice_id)[0]

    @staticmethod
    def _seed(seed: int | None) -> None:
        if seed is not None:
            mx.random.seed(seed)

    @staticmethod
    def _audio(results: Iterable[GenerationResult]) -> tuple[np.ndarray, int]:
        items = list(results)
        if not items:
            raise RuntimeError("MLX Qwen returned no audio.")
        rates = {int(item.sample_rate) for item in items}
        if len(rates) != 1:
            raise RuntimeError("MLX Qwen returned inconsistent sampling rates.")
        return np.concatenate([np.asarray(item.audio, dtype=np.float32).reshape(-1) for item in items]), rates.pop()

    def _generate_once(self, request: api.GenerateRequest) -> tuple[np.ndarray, int]:
        self._seed(request.seed)
        language = request.language or api.LANGUAGE
        voice_id = request.voice_id or "preset:Ryan"
        if voice_id.startswith("preset:"):
            model = self._load("custom")
            return self._audio(
                model.generate_custom_voice(
                    text=request.text,
                    speaker=voice_id.removeprefix("preset:"),
                    language=language,
                    instruct=api._instruction(request.voice),
                )
            )
        model = self._load("clone")
        reference, transcript = self._reference(voice_id)
        return self._audio(
            model.generate(
                text=request.text,
                ref_audio=str(reference),
                ref_text=transcript,
                lang_code=language,
            )
        )

    def _generate_many_once(self, requests: list[api.GenerateRequest]) -> tuple[list[np.ndarray], int]:
        if not requests:
            return [], 0
        first = requests[0]
        self._seed(first.seed)
        language = first.language or api.LANGUAGE
        voice_id = first.voice_id or "preset:Ryan"
        if voice_id.startswith("preset:"):
            model = self._load("custom")
            generated = model.batch_generate(
                texts=[request.text for request in requests],
                voices=[(request.voice_id or "preset:Ryan").removeprefix("preset:") for request in requests],
                instructs=[api._instruction(request.voice) for request in requests],
                lang_code=language,
            )
        else:
            model = self._load("clone")
            references = [self._reference(request.voice_id or "") for request in requests]
            generated = model.batch_generate(
                texts=[request.text for request in requests],
                ref_audios=[str(reference) for reference, _transcript in references],
                ref_texts=[transcript for _reference, transcript in references],
                lang_code=language,
            )

        by_sequence: dict[int, list[np.ndarray]] = {index: [] for index in range(len(requests))}
        sampling_rate = None
        for result in generated:
            if result.sequence_idx not in by_sequence:
                raise RuntimeError(f"MLX Qwen returned unexpected sequence {result.sequence_idx}.")
            rate = int(result.sample_rate)
            if sampling_rate is not None and sampling_rate != rate:
                raise RuntimeError("MLX Qwen returned inconsistent batch sampling rates.")
            sampling_rate = rate
            by_sequence[result.sequence_idx].append(np.asarray(result.audio, dtype=np.float32).reshape(-1))
        missing = [index for index, parts in by_sequence.items() if not parts]
        if missing or sampling_rate is None:
            raise RuntimeError(f"MLX Qwen omitted batch sequences: {missing}.")
        return [np.concatenate(by_sequence[index]) for index in range(len(requests))], sampling_rate

    def _validate_audio(self, request: api.GenerateRequest, audio: np.ndarray, rate: int) -> SpeakerCheck:
        return api.validate_speaker(self._speaker_guard, request, audio, rate)

    def _generate_valid_audio(
        self,
        request: api.GenerateRequest,
        *,
        initial: tuple[np.ndarray, int] | None = None,
    ) -> tuple[np.ndarray, int, float | None, int]:
        return api.generate_valid_audio(
            self._generate_once, self._speaker_guard, request, initial=initial, label="MLX Qwen output"
        )

    def generate(self, request: api.GenerateRequest) -> tuple[bytes, int, float | None, int]:
        with self._lock:
            audio, rate, similarity, attempts = self._generate_valid_audio(request)
            encoded, duration = api._encode_mp3(audio, rate)
            return encoded, duration, similarity, attempts

    def generate_batch(self, requests: list[api.GenerateRequest]) -> list[tuple[bytes, int, float | None, int]]:
        with self._lock:
            generated: list[tuple[np.ndarray, int, float | None, int] | None] = [None] * len(requests)
            groups: dict[tuple[str, int | None], list[int]] = {}
            for index, request in enumerate(requests):
                groups.setdefault((request.voice_id or "preset:Ryan", request.seed), []).append(index)

            for indices in groups.values():
                group = [requests[index] for index in indices]
                if len(group) == 1:
                    generated[indices[0]] = self._generate_valid_audio(group[0])
                    continue
                # Each native output is the item's first attempt; rejected items
                # are retried individually with their next attempt seed.
                audios, rate = self._generate_many_once(group)
                for index, request, audio in zip(indices, group, audios, strict=True):
                    generated[index] = self._generate_valid_audio(request, initial=(audio, rate))

            results = []
            for item in generated:
                if item is None:
                    raise RuntimeError("MLX Qwen batch generation did not produce every requested item.")
                audio, rate, similarity, attempts = item
                encoded, duration = api._encode_mp3(audio, rate)
                results.append((encoded, duration, similarity, attempts))
            return results

    def design(self, request: api.DesignVoiceRequest) -> tuple[StoredVoice, float | None, int]:
        with self._lock:
            model = self._load("design")

            def render(description: str, seed: int | None) -> tuple[np.ndarray, int]:
                self._seed(seed)
                return self._audio(
                    model.generate_voice_design(
                        text=api.DESIGN_TEXT,
                        language=request.language or api.LANGUAGE,
                        instruct=api._instruction(description),
                    )
                )

            return api.design_stored_voice(self._speaker_guard, self._voices, request, render, label="Qwen3 MLX voice design")

    def materialize_preset(
        self,
        request: api.PresetVoiceRequest,
    ) -> tuple[StoredVoice, float | None, int]:
        """Render an official preset once and persist it as a clone reference."""
        with self._lock:
            audio, rate = self._generate_once(
                api.GenerateRequest(
                    text=api.DESIGN_TEXT,
                    voice=request.voice,
                    voice_id=request.voice_id,
                    language=request.language,
                    seed=request.seed,
                    quality_attempts=1,
                )
            )
            validate_generated_audio(audio, rate)
            similarity = api.check_preset_distinct(self._speaker_guard, request, audio, rate)
            description = f"Official Qwen preset {request.voice_id.removeprefix('preset:')}: {request.voice}"
            stored = self._voices.create(description, api.DESIGN_TEXT, audio, rate)
            self._speaker_guard.calibrate(stored.id)
            return stored, similarity, 1


api.runtime = MLXQwenRuntime()
app = api.app
app.title = "Story Manager Qwen3-TTS MLX Adapter"
