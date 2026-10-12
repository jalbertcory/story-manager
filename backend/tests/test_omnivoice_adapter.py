import numpy as np
import pytest
import wave

from services.omnivoice.audio_quality import AudioQualityError, validate_generated_audio
from services.omnivoice.normalization import prepare_for_normalization
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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("In the 1990s it rained.", "In the nineteen nineties it rained."),
        ("The mid-1960s and 1970's.", "The mid-nineteen sixties and nineteen seventies."),
        ("The 1800s, 1910s, 2000s, and 2010s.", "The eighteen hundreds, nineteen tens, two thousands, and twenty tens."),
        ("She paid $1,250.50 for 12 books.", "She paid $1,250 and 50 cents for 12 books."),
        ("It cost $0.50, $1.01, $5.00, or $3.", "It cost 50 cents, $1 and 1 cent, $5, or $3."),
    ],
)
def test_prepares_decades_and_cents_for_text_normalization(text, expected):
    assert prepare_for_normalization(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "She was in her 20s, back in the '80s.",
        "Room 1990s1 and 12.50 dollars.",
        "He laughed [laughter] in 1999.",
    ],
)
def test_leaves_forms_the_upstream_normalizer_handles_unchanged(text):
    assert prepare_for_normalization(text) == text


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
