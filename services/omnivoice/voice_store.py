"""Durable reference samples used as reusable OmniVoice voices."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import uuid
import wave

import numpy as np

_VOICE_ID_RE = re.compile(r"^omnivoice-[0-9a-f]{32}$")


@dataclass(frozen=True)
class StoredVoice:
    id: str
    model: str
    instruct: str
    ref_text: str
    sample_file: str


class VoiceStore:
    """Store enrollment audio and metadata on a persistent filesystem."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create(
        self,
        *,
        model: str,
        instruct: str,
        ref_text: str,
        audio: np.ndarray,
        sampling_rate: int,
    ) -> StoredVoice:
        self.root.mkdir(parents=True, exist_ok=True)
        voice_id = f"omnivoice-{uuid.uuid4().hex}"
        sample_file = f"{voice_id}.wav"
        stored = StoredVoice(
            id=voice_id,
            model=model,
            instruct=instruct,
            ref_text=ref_text,
            sample_file=sample_file,
        )
        self._write_wav(self.root / sample_file, audio, sampling_rate)
        metadata_path = self.root / f"{voice_id}.json"
        temporary_path = metadata_path.with_suffix(".json.tmp")
        temporary_path.write_text(json.dumps(asdict(stored), indent=2), encoding="utf-8")
        temporary_path.replace(metadata_path)
        return stored

    def get(self, voice_id: str) -> StoredVoice:
        if not _VOICE_ID_RE.fullmatch(voice_id):
            raise KeyError(f"Invalid OmniVoice voice ID: {voice_id!r}")
        metadata_path = self.root / f"{voice_id}.json"
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            stored = StoredVoice(**data)
        except (FileNotFoundError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise KeyError(f"Unknown OmniVoice voice ID: {voice_id}") from exc
        expected_sample_file = f"{voice_id}.wav"
        if (
            stored.id != voice_id
            or stored.sample_file != expected_sample_file
            or not (self.root / expected_sample_file).is_file()
        ):
            raise KeyError(f"Incomplete OmniVoice voice: {voice_id}")
        return stored

    def sample_path(self, voice_id: str) -> Path:
        return self.root / self.get(voice_id).sample_file

    @staticmethod
    def _write_wav(path: Path, audio: np.ndarray, sampling_rate: int) -> None:
        pcm = np.clip(audio * 32767, -32768, 32767).astype("<i2")
        temporary_path = path.with_suffix(".wav.tmp")
        with wave.open(str(temporary_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sampling_rate)
            output.writeframes(pcm.tobytes())
        temporary_path.replace(path)
