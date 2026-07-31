DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM imported_audiobooks
        WHERE name = 'Pre-existing imported edition'
    ) THEN
        RAISE EXCEPTION '0024 downgrade removed a pre-existing imported edition';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM imported_audiobook_cues
        WHERE method = 'transcribed'
    ) THEN
        RAISE EXCEPTION '0024 downgrade removed pre-existing imported audiobook data';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'audiobook_settings'
          AND column_name = 'transcription_provider'
    ) OR NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'imported_audiobooks'
          AND column_name = 'alignment_error'
    ) OR NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'imported_audiobook_tracks'
          AND column_name = 'alignment_score'
    ) THEN
        RAISE EXCEPTION '0025 downgrade removed pre-existing columns';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM audiobook_settings
        WHERE transcription_provider = 'whisperx'
          AND transcription_base_url = 'http://preexisting-whisper:8002'
    ) THEN
        RAISE EXCEPTION '0025 downgrade removed pre-existing transcription settings';
    END IF;
END
$$;
