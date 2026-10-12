DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'audiobook_settings'
          AND column_name = 'tts_voice_similarity_threshold'
    ) THEN
        RAISE EXCEPTION '0044 left the absolute similarity threshold column behind';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM audiobook_settings
        WHERE tts_provider <> 'drift-disabled'
          AND tts_voice_drift_margin <> 3.0
    ) THEN
        RAISE EXCEPTION '0044 did not move enabled thresholds to the default drift margin';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM audiobook_settings
        WHERE tts_provider = 'drift-disabled'
          AND tts_voice_drift_margin = 0.0
    ) THEN
        RAISE EXCEPTION '0044 did not keep a disabled threshold disabled';
    END IF;
END $$;

INSERT INTO audiobook_settings (tts_provider) VALUES ('drift-default');

DO $$
BEGIN
    IF (SELECT tts_voice_drift_margin FROM audiobook_settings WHERE tts_provider = 'drift-default') <> 3.0 THEN
        RAISE EXCEPTION '0044 did not set the drift margin server default';
    END IF;
END $$;

DELETE FROM audiobook_settings WHERE tts_provider = 'drift-default';

UPDATE audiobook_settings
SET tts_voice_drift_margin = 2.0
WHERE tts_provider <> 'drift-disabled';
