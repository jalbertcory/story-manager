import numpy as np
import pytest
import wave

from services.omnivoice.audio_quality import AudioQualityError, validate_generated_audio
from services.omnivoice.prompt import translate_generation_prompt
from services.omnivoice.voice_store import VoiceStore


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


def test_voice_store_persists_reference_audio_and_metadata(tmp_path):
    store = VoiceStore(tmp_path / "voices")
    audio = np.linspace(-0.25, 0.25, 2400, dtype=np.float32)

    created = store.create(
        model="k2-fsa/OmniVoice",
        instruct="female, low pitch, british accent",
        ref_text="A reusable reference sentence.",
        audio=audio,
        sampling_rate=24000,
    )

    loaded = VoiceStore(tmp_path / "voices").get(created.id)
    assert loaded == created
    assert store.sample_path(created.id).is_file()
    with wave.open(str(store.sample_path(created.id)), "rb") as sample:
        assert sample.getframerate() == 24000
        assert sample.getnchannels() == 1
        assert sample.getnframes() == len(audio)


def test_voice_store_rejects_untrusted_or_unknown_ids(tmp_path):
    store = VoiceStore(tmp_path / "voices")

    with pytest.raises(KeyError, match="Invalid"):
        store.get("../../private")
    with pytest.raises(KeyError, match="Unknown"):
        store.get("omnivoice-00000000000000000000000000000000")
