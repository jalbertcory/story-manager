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
