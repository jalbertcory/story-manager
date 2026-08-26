import pytest

from services.tts_consistency import candidate_has_enough_speech, seed_for_attempt, voice_instruction


def test_seed_for_attempt_is_reproducible_and_distinct():
    assert [seed_for_attempt(100, attempt) for attempt in range(1, 4)] == [100, 101, 102]
    assert seed_for_attempt(2_147_483_647, 2) == 0
    assert seed_for_attempt(None, 3) is None


def test_seed_for_attempt_rejects_non_positive_attempt():
    with pytest.raises(ValueError, match="at least 1"):
        seed_for_attempt(100, 0)


def test_speaker_similarity_skips_subsecond_utterances():
    assert candidate_has_enough_speech(15_999, 16_000) is False
    assert candidate_has_enough_speech(16_000, 16_000) is True


def test_speaker_similarity_rejects_invalid_sampling_rate():
    with pytest.raises(ValueError, match="positive"):
        candidate_has_enough_speech(1, 0)


def test_voice_instruction_preserves_distinctive_prose_after_profile_tokens():
    instruction = voice_instruction(
        "[gender-female][pitch-high][speed-fast] Smoky timbre, crisp consonants, and clipped phrasing."
    )

    assert "female gender" in instruction
    assert "high pitch" in instruction
    assert "fast speed" in instruction
    assert "Smoky timbre, crisp consonants, and clipped phrasing." in instruction
