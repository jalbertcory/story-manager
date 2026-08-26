DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM books
        WHERE title IN ('Provider Saga One', 'Provider Saga Two')
          AND audiobook_tts_provider IS DISTINCT FROM 'qwen3'
    ) THEN
        RAISE EXCEPTION '0038 did not propagate the series Qwen lock';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM books
        WHERE title = 'Provider Standalone'
          AND audiobook_tts_provider = 'omnivoice'
    ) THEN
        RAISE EXCEPTION '0038 did not backfill a standalone OmniVoice lock';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM books
        WHERE title = 'Provider Mixed History'
          AND audiobook_tts_provider IS NOT NULL
    ) THEN
        RAISE EXCEPTION '0038 silently chose a provider for mixed historical voices';
    END IF;
END $$;
