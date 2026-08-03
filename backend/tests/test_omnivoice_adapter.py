import numpy as np
import pytest

from services.omnivoice.audio_quality import AudioQualityError, validate_generated_audio
from services.omnivoice.prompt import translate_generation_prompt


def test_translates_legacy_voice_profile_to_official_omnivoice_attributes():
    prompt = translate_generation_prompt(
        "[gender-female][pitch-low][speed-fast][age-middle][accent-british]",
        "A line of dialogue.",
    )

    assert prompt.text == "A line of dialogue."
    assert prompt.instruct == "female, low pitch, middle-aged, british accent"
    assert prompt.speed == 1.15


def test_preserves_supported_audio_tags_and_removes_unsupported_tags():
    prompt = translate_generation_prompt(
        "[gender-neutral][pitch-medium][speed-normal]",
        "[whisper] Quietly. [laughter] [shout] Loudly.",
    )

    assert prompt.text == "Quietly. [laughter] Loudly."
    assert prompt.instruct == "moderate pitch, whisper"
    assert prompt.speed == 1.0


def test_accepts_native_omnivoice_instruction():
    prompt = translate_generation_prompt(
        "male, elderly, low pitch, american accent",
        "Hello.",
    )

    assert prompt.instruct == "male, elderly, low pitch, american accent"


def test_rejects_stationary_mechanical_noise():
    sampling_rate = 24000
    rng = np.random.default_rng(42)
    samples = rng.normal(0, 0.08, sampling_rate * 2).astype(np.float32)

    with pytest.raises(AudioQualityError, match="stationary mechanical noise"):
        validate_generated_audio(samples, sampling_rate)


def test_accepts_speech_like_audio_with_natural_variation():
    sampling_rate = 24000
    time = np.arange(sampling_rate * 2) / sampling_rate
    envelope = np.maximum(0, np.sin(2 * np.pi * 1.3 * time)) ** 2
    samples = envelope * (
        0.12 * np.sin(2 * np.pi * 130 * time) + 0.06 * np.sin(2 * np.pi * 260 * time) + 0.03 * np.sin(2 * np.pi * 390 * time)
    )

    report = validate_generated_audio(samples.astype(np.float32), sampling_rate)

    assert report.has_stationary_mechanical_noise is False
