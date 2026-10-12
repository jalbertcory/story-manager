DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'audiobook_settings'
          AND column_name = 'tts_voice_drift_margin'
    ) THEN
        RAISE EXCEPTION '0044 drift margin column survived downgrade';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM audiobook_settings
        WHERE tts_provider <> 'drift-disabled'
          AND tts_voice_similarity_threshold <> 0.45
    ) THEN
        RAISE EXCEPTION '0044 downgrade did not restore the default similarity threshold';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM audiobook_settings
        WHERE tts_provider = 'drift-disabled'
          AND tts_voice_similarity_threshold = 0.0
    ) THEN
        RAISE EXCEPTION '0044 downgrade did not keep a disabled check disabled';
    END IF;
END $$;

DELETE FROM audiobook_settings WHERE tts_provider = 'drift-disabled';
