DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM audiobook_settings
        WHERE tts_max_block_chars <> 500
           OR tts_voice_similarity_threshold <> 0.45
           OR tts_quality_attempts <> 3
    ) THEN
        RAISE EXCEPTION '0037 did not apply voice-consistency defaults';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM audiobook_characters
        WHERE name = 'Voice Migration Narrator' AND tts_seed IS NULL
    ) THEN
        RAISE EXCEPTION '0037 did not preserve the existing character';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM audiobook_series_characters
        WHERE series_name = 'Voice Migration Series' AND tts_seed IS NULL
    ) THEN
        RAISE EXCEPTION '0037 did not preserve the existing series profile';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM audiobook_sentences
        WHERE html_element_id = 'existing-sentence'
          AND generation_group_id IS NULL
          AND voice_similarity IS NULL
          AND tts_attempts IS NULL
    ) THEN
        RAISE EXCEPTION '0037 did not preserve the existing sentence';
    END IF;
END $$;

UPDATE audiobook_characters
SET tts_seed = 12345
WHERE name = 'Voice Migration Narrator';

UPDATE audiobook_series_characters
SET tts_seed = 12345
WHERE series_name = 'Voice Migration Series';

UPDATE audiobook_sentences
SET generation_group_id = 'migration-group',
    voice_similarity = 0.8,
    tts_attempts = 2
WHERE html_element_id = 'existing-sentence';
