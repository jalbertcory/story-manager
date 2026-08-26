DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name IN (
            'audiobook_settings',
            'audiobook_series_characters',
            'audiobook_characters',
            'audiobook_sentences'
        )
          AND column_name IN (
            'tts_max_block_chars',
            'tts_voice_similarity_threshold',
            'tts_quality_attempts',
            'tts_seed',
            'generation_group_id',
            'voice_similarity',
            'tts_attempts'
        )
    ) THEN
        RAISE EXCEPTION '0037 voice-consistency columns survived downgrade';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM audiobook_characters WHERE name = 'Voice Migration Narrator'
    ) OR NOT EXISTS (
        SELECT 1 FROM audiobook_sentences WHERE html_element_id = 'existing-sentence'
    ) THEN
        RAISE EXCEPTION '0037 downgrade removed existing audiobook data';
    END IF;
END $$;
