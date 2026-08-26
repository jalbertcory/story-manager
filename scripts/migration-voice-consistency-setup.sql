INSERT INTO audiobook_settings (tts_provider)
SELECT 'omnivoice'
WHERE NOT EXISTS (SELECT 1 FROM audiobook_settings);

INSERT INTO audiobook_series_characters (
    series_name,
    canonical_name,
    name,
    is_narrator
)
VALUES (
    'Voice Migration Series',
    'voice migration narrator',
    'Voice Migration Narrator',
    true
)
ON CONFLICT (series_name, canonical_name) DO NOTHING;

INSERT INTO audiobook_characters (
    book_id,
    series_character_id,
    name,
    is_narrator
)
SELECT
    books.id,
    profiles.id,
    'Voice Migration Narrator',
    true
FROM books
CROSS JOIN audiobook_series_characters AS profiles
WHERE books.title = 'Migration Test'
  AND profiles.series_name = 'Voice Migration Series'
  AND NOT EXISTS (
      SELECT 1
      FROM audiobook_characters
      WHERE audiobook_characters.book_id = books.id
        AND audiobook_characters.name = 'Voice Migration Narrator'
  );
