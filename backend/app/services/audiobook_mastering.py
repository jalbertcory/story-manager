"""Chapter mastering: even out sentence loudness and pauses before encoding.

Sentence clips are generated independently, so each arrives at its own level
and with however much silence the model happened to leave around the words.
Played back to back that reads as a narrator who keeps changing distance from
the microphone and pausing at random. Mastering trims each clip to its speech,
brings the speech to one loudness, and inserts pauses chosen from the text.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from .audiobook_block_split import PcmSamples, frame_levels_db
from .subprocesses import communicate_bounded

_FRAME_MS = 10
# Frames quieter than this are never speech, whatever the clip's own level.
_SPEECH_FLOOR_DB = -52.0
# Word endings and breaths this far below the clip's loudest frame are kept.
_SPEECH_RANGE_DB = 36.0
# Loudness is measured on frames within this range of the clip's mean level,
# so trailing consonants and room tone do not drag the measurement down.
_LOUDNESS_GATE_DB = 10.0
TARGET_SPEECH_DB = -21.0
_MAX_GAIN_DB = 15.0
_PEAK_CEILING = 10 ** (-1.0 / 20)
_LEAD_PAD_MS = 20
_TRAIL_PAD_MS = 60
_FADE_MS = 8
# A clip with no speech still needs a nonzero slot in the media overlay.
_SPEECHLESS_MS = 120

PAUSE_SENTENCE_MS = 380
PAUSE_SPEAKER_CHANGE_MS = 480
PAUSE_CLAUSE_MS = 160
PAUSE_CONTINUATION_MS = 220
PAUSE_CHAPTER_END_MS = 900

_CLOSERS = "\"'”’»)]} \t\r\n*_"
_SENTENCE_ENDINGS = ".!?…"
_CLAUSE_ENDINGS = ",;:—–-"


@dataclass(frozen=True)
class MasteredClip:
    samples: PcmSamples
    has_speech: bool
    gain_db: float


def _speech_level_db(levels: NDArray[np.float64]) -> float:
    """Gated mean level of the speech frames, in dBFS."""
    power = 10.0 ** (levels / 10.0)
    ungated = 10.0 * np.log10(float(np.mean(power)))
    gated = power[levels >= ungated - _LOUDNESS_GATE_DB]
    return float(10.0 * np.log10(float(np.mean(gated if gated.size else power))))


def master_clip(samples: PcmSamples, rate: int) -> MasteredClip:
    """Trim a sentence clip to its speech and bring that speech to the target level."""
    frame = max(1, rate * _FRAME_MS // 1000)
    levels = frame_levels_db(samples, rate)
    loudest = float(levels.max()) if levels.size else -120.0
    if loudest < _SPEECH_FLOOR_DB:
        return MasteredClip(np.zeros(rate * _SPEECHLESS_MS // 1000, dtype=np.int16), False, 0.0)

    threshold = max(_SPEECH_FLOOR_DB, loudest - _SPEECH_RANGE_DB)
    active = np.flatnonzero(levels >= threshold)
    start = max(0, int(active[0]) * frame - rate * _LEAD_PAD_MS // 1000)
    end = min(len(samples), (int(active[-1]) + 1) * frame + rate * _TRAIL_PAD_MS // 1000)
    speech = samples[start:end].astype(np.float64)

    gain_db = TARGET_SPEECH_DB - _speech_level_db(levels[slice(int(active[0]), int(active[-1]) + 1)])
    gain_db = float(np.clip(gain_db, -_MAX_GAIN_DB, _MAX_GAIN_DB))
    peak = float(np.max(np.abs(speech))) / 32768.0
    if peak > 0.0:
        # Lowering the gain keeps the waveform intact; a clip this peaky ends up
        # slightly under target rather than distorted.
        gain_db = min(gain_db, float(20.0 * np.log10(_PEAK_CEILING / peak)))
    speech *= 10.0 ** (gain_db / 20.0)

    fade = min(rate * _FADE_MS // 1000, len(speech) // 2)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, endpoint=False)
        speech[:fade] *= ramp
        speech[-fade:] *= ramp[::-1]
    mastered: PcmSamples = np.clip(np.rint(speech), -32768, 32767).astype(np.int16)
    return MasteredClip(mastered, True, gain_db)


def pause_after_ms(text: str, *, speaker_changes: bool, last_in_chapter: bool) -> int:
    """Silence to leave after a sentence clip, chosen from how its text ends."""
    if last_in_chapter:
        return PAUSE_CHAPTER_END_MS
    ending = text.rstrip(_CLOSERS)[-1:]
    if ending in _SENTENCE_ENDINGS and ending:
        return PAUSE_SPEAKER_CHANGE_MS if speaker_changes else PAUSE_SENTENCE_MS
    if ending in _CLAUSE_ENDINGS and ending:
        return PAUSE_CLAUSE_MS
    return PAUSE_CONTINUATION_MS


def silence(duration_ms: int, rate: int) -> PcmSamples:
    return np.zeros(rate * duration_ms // 1000, dtype=np.int16)


async def decode_clip(ffmpeg: str, path: Path, rate: int) -> PcmSamples:
    """Decode one sentence clip to mono 16-bit PCM at the chapter sample rate."""
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "s16le",
        "-ac",
        "1",
        "-ar",
        str(rate),
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await communicate_bounded(process, description="ffmpeg sentence decode")
    if process.returncode:
        message = stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"ffmpeg could not decode {path.name}: {message}")
    return np.frombuffer(stdout[: len(stdout) // 2 * 2], dtype="<i2").astype(np.int16)


async def encode_mp3(ffmpeg: str, samples: PcmSamples, rate: int, bitrate: str, output: Path) -> None:
    """Encode mono 16-bit PCM to an MP3 file.

    Writing to a seekable file lets the encoder record its delay and padding,
    so the clip decodes back to exactly the samples given here.
    """
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-v",
        "error",
        "-f",
        "s16le",
        "-ar",
        str(rate),
        "-ac",
        "1",
        "-i",
        "pipe:0",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        "-y",
        str(output),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await communicate_bounded(process, description="ffmpeg sentence encode", stdin=samples.astype("<i2").tobytes())
    if process.returncode:
        message = stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"ffmpeg could not encode a sentence clip: {message}")
