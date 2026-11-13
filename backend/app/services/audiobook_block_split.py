"""Recover sentence clips from one multi-sentence TTS generation.

Generating adjacent sentences as one block keeps the voice steady, but the
model returns a single waveform. The sentence boundaries are recovered from
its pauses: of all the ways to pick one pause per boundary, take the one whose
slices best match how long each sentence should take to say.
"""

from __future__ import annotations

import re

import numpy as np
from numpy.typing import NDArray

PcmSamples = NDArray[np.int16]

_FRAME_MS = 10
_SILENCE_FLOOR_DB = -60.0
# Pauses sit this far below the block's loudest frame, whatever its level.
_SILENCE_RANGE_DB = 30.0
_MIN_SILENCE_MS = 60
# A sentence-final pause is about as long as this many spoken characters.
_PAUSE_WEIGHT = 5.0
# Longer pauses are likelier sentence ends; this only breaks near-ties.
_PAUSE_REWARD = 0.12
_PAUSE_REWARD_CAP_MS = 600
# Cutting where there is no pause is a last resort.
_NO_PAUSE_PENALTY = 0.6
_MIN_SPEECH_MS = 60
# Sentences of at least this many characters must be spoken at a pace within
# these bounds of the block's own; anything else is a misplaced boundary.
_PACE_CHECK_MIN_CHARS = 12
_PACE_RATIO_BOUNDS = (0.4, 2.5)
# A block whose loudest frame is below this has no speech in it at all.
_BLOCK_SPEECH_FLOOR_DB = -52.0


class BlockSplitError(RuntimeError):
    """The block's pauses do not line up with its sentences."""


def frame_levels_db(samples: PcmSamples, rate: int) -> NDArray[np.float64]:
    frame = max(1, rate * _FRAME_MS // 1000)
    count = len(samples) // frame
    if count == 0:
        return np.empty(0, dtype=np.float64)
    frames = samples[: count * frame].astype(np.float64).reshape(count, frame) / 32768.0
    levels: NDArray[np.float64] = 10.0 * np.log10(np.mean(frames * frames, axis=1) + 1e-12)
    return levels


def silence_intervals(levels: NDArray[np.float64]) -> list[tuple[int, int]]:
    """Return ``(start_ms, end_ms)`` for each pause in a block's frame levels."""
    if not levels.size:
        return []
    threshold = max(_SILENCE_FLOOR_DB, float(levels.max()) - _SILENCE_RANGE_DB)
    quiet = levels < threshold
    edges = np.flatnonzero(np.diff(np.concatenate(([False], quiet, [False])).astype(np.int8)))
    intervals: list[tuple[int, int]] = []
    for start, end in zip(edges[::2], edges[1::2], strict=True):
        if (int(end) - int(start)) * _FRAME_MS >= _MIN_SILENCE_MS:
            intervals.append((int(start) * _FRAME_MS, int(end) * _FRAME_MS))
    return intervals


def _spoken_chars(text: str) -> int:
    return max(1, len(re.sub(r"\W+", "", text)))


def estimated_block_boundaries(
    duration_ms: int,
    texts: list[str],
    silences: list[tuple[int, int]],
) -> list[int]:
    """Choose monotonic slice boundaries, one pause per sentence break.

    Every boundary is chosen jointly, so one ambiguous pause cannot push the
    rest of the block out of step the way nearest-pause snapping did.
    """
    count = len(texts)
    if count <= 1:
        return [0, duration_ms]

    speech_start, speech_end = 0, duration_ms
    interior = list(silences)
    if interior and interior[0][0] <= _FRAME_MS:
        speech_start = interior.pop(0)[1]
    if interior and interior[-1][1] >= duration_ms - 2 * _FRAME_MS:
        speech_end = interior.pop()[0]
    if speech_end <= speech_start:
        speech_start, speech_end = 0, duration_ms
        interior = []

    weights = [_spoken_chars(text) + _PAUSE_WEIGHT for text in texts]
    weights[0] -= _PAUSE_WEIGHT / 2
    weights[-1] -= _PAUSE_WEIGHT / 2
    span = speech_end - speech_start
    total_weight = sum(weights)
    expected = [span * weight / total_weight for weight in weights]

    # Candidate cut points: the middle of every pause, plus an unpaused cut at
    # each proportional estimate so a block with too few pauses still splits.
    candidates: list[tuple[int, float]] = [
        (
            (start + end) // 2,
            -_PAUSE_REWARD * min(end - start, _PAUSE_REWARD_CAP_MS) / _PAUSE_REWARD_CAP_MS,
        )
        for start, end in interior
        if speech_start < (start + end) // 2 < speech_end
    ]
    cumulative = 0.0
    for length in expected[:-1]:
        cumulative += length
        candidates.append((speech_start + round(cumulative), _NO_PAUSE_PENALTY))
    candidates.sort()

    minimum_gap = max(1, min(150, span // (count * 2)))

    def segment_cost(index: int, start: int, end: int) -> float:
        deviation = (end - start - expected[index]) / (expected[index] + 300.0)
        return deviation * deviation

    infinity = float("inf")
    # best[j] is the cheapest way to end the current sentence at candidate j.
    best = [
        segment_cost(0, speech_start, position) + cost if position - speech_start >= minimum_gap else infinity
        for position, cost in candidates
    ]
    history: list[list[int]] = []
    for sentence_index in range(1, count - 1):
        following = [infinity] * len(candidates)
        previous = [-1] * len(candidates)
        for j, (position, cost) in enumerate(candidates):
            for i in range(j):
                if best[i] == infinity or position - candidates[i][0] < minimum_gap:
                    continue
                total = best[i] + segment_cost(sentence_index, candidates[i][0], position) + cost
                if total < following[j]:
                    following[j] = total
                    previous[j] = i
        history.append(previous)
        best = following

    final_index = -1
    final_cost = infinity
    for j, (position, _cost) in enumerate(candidates):
        if best[j] == infinity or speech_end - position < minimum_gap:
            continue
        total = best[j] + segment_cost(count - 1, position, speech_end)
        if total < final_cost:
            final_cost = total
            final_index = j

    if final_index < 0:
        # Too short to honour the minimum gap anywhere: fall back to an even,
        # strictly increasing split so every sentence still gets a slice.
        step = duration_ms / count
        inner = [max(index, min(duration_ms - (count - index), round(step * index))) for index in range(1, count)]
        return [0, *inner, duration_ms]

    chosen = [final_index]
    for previous in reversed(history):
        chosen.append(previous[chosen[-1]])
    return [0, *(candidates[index][0] for index in reversed(chosen)), duration_ms]


def split_block(samples: PcmSamples, rate: int, texts: list[str]) -> list[PcmSamples]:
    """Slice a block into one clip per sentence, or raise if the slices look wrong."""
    if len(texts) == 1:
        return [samples]
    levels = frame_levels_db(samples, rate)
    duration_ms = len(samples) * 1000 // rate
    silences = silence_intervals(levels)
    boundaries = estimated_block_boundaries(duration_ms, texts, silences)

    if not levels.size or float(levels.max()) <= _BLOCK_SPEECH_FLOOR_DB:
        # A silent block has nothing to line sentences up with, and its slices
        # would be stored as finished audio.
        raise BlockSplitError("block contains no speech")
    speech = levels >= max(_SILENCE_FLOOR_DB, float(levels.max()) - _SILENCE_RANGE_DB)
    spoken_ms = [
        int(np.count_nonzero(speech[slice(start // _FRAME_MS, end // _FRAME_MS)])) * _FRAME_MS
        for start, end in zip(boundaries, boundaries[1:])
    ]
    total_chars = sum(_spoken_chars(text) for text in texts)
    block_pace = total_chars / max(1, sum(spoken_ms))
    for index, (text, milliseconds) in enumerate(zip(texts, spoken_ms, strict=True)):
        chars = _spoken_chars(text)
        if milliseconds < _MIN_SPEECH_MS:
            raise BlockSplitError(f"slice {index + 1} of {len(texts)} has no speech")
        if chars >= _PACE_CHECK_MIN_CHARS:
            ratio = (chars / milliseconds) / block_pace
            if not _PACE_RATIO_BOUNDS[0] <= ratio <= _PACE_RATIO_BOUNDS[1]:
                raise BlockSplitError(f"slice {index + 1} of {len(texts)} is spoken at {ratio:.1f}x the block's pace")

    return [samples[slice(start * rate // 1000, end * rate // 1000)] for start, end in zip(boundaries, boundaries[1:])]
