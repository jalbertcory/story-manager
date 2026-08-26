"""Persistent designed voice references for Qwen3-TTS cloning."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import uuid

import numpy as np

_VOICE_ID_RE = re.compile(r"^qwen3-[0-9a-f]{32}$")


@dataclass(frozen=True)
class StoredVoice:
    id: str
    description: str
    ref_text: str
    sample_file: str


class VoiceStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def create(self, description: str, ref_text: str, audio: np.ndarray, sampling_rate: int) -> StoredVoice:
        import soundfile as sf

        self.root.mkdir(parents=True, exist_ok=True)
        voice_id = f"qwen3-{uuid.uuid4().hex}"
        sample_file = f"{voice_id}.wav"
        stored = StoredVoice(voice_id, description, ref_text, sample_file)
        temporary_audio = self.root / f"{sample_file}.tmp"
        sf.write(temporary_audio, audio, sampling_rate, format="WAV", subtype="PCM_16")
        temporary_audio.replace(self.root / sample_file)
        temporary_metadata = self.root / f"{voice_id}.json.tmp"
        temporary_metadata.write_text(json.dumps(asdict(stored), indent=2), encoding="utf-8")
        temporary_metadata.replace(self.root / f"{voice_id}.json")
        return stored

    def get(self, voice_id: str) -> StoredVoice:
        if not _VOICE_ID_RE.fullmatch(voice_id):
            raise KeyError(f"Invalid Qwen3 voice ID: {voice_id!r}")
        try:
            stored = StoredVoice(**json.loads((self.root / f"{voice_id}.json").read_text(encoding="utf-8")))
        except (FileNotFoundError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise KeyError(f"Unknown Qwen3 voice ID: {voice_id}") from exc
        if (
            stored.id != voice_id
            or stored.sample_file != f"{voice_id}.wav"
            or not self.sample_path_unchecked(stored).is_file()
        ):
            raise KeyError(f"Incomplete Qwen3 voice ID: {voice_id}")
        return stored

    def sample_path_unchecked(self, stored: StoredVoice) -> Path:
        return self.root / stored.sample_file

    def sample_path(self, voice_id: str) -> Path:
        return self.sample_path_unchecked(self.get(voice_id))
