INSERT INTO audiobook_settings (tts_provider)
SELECT 'omnivoice'
WHERE NOT EXISTS (SELECT 1 FROM audiobook_settings);

UPDATE audiobook_settings SET tts_voice_similarity_threshold = 0.62;

INSERT INTO audiobook_settings (tts_provider, tts_voice_similarity_threshold)
VALUES ('drift-disabled', -1.0);
