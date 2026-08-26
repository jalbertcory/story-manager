INSERT INTO books (title, author, source_type, series)
VALUES
    ('Provider Saga One', 'Story Manager', 'epub', 'Provider Migration Saga'),
    ('Provider Saga Two', 'Story Manager', 'epub', 'Provider Migration Saga'),
    ('Provider Standalone', 'Story Manager', 'epub', NULL),
    ('Provider Mixed History', 'Story Manager', 'epub', NULL),
    ('Provider Active With Deleted History', 'Story Manager', 'epub', 'Deleted Provider Migration Saga'),
    ('Provider Deleted History', 'Story Manager', 'epub', 'Deleted Provider Migration Saga');

UPDATE books
SET deleted_at = CURRENT_TIMESTAMP
WHERE title = 'Provider Deleted History';

INSERT INTO audiobook_characters (book_id, name, is_narrator, tts_voice_provider)
SELECT id, 'Narrator', true, 'qwen3'
FROM books
WHERE title = 'Provider Saga One';

INSERT INTO audiobook_characters (book_id, name, is_narrator, tts_voice_provider)
SELECT id, 'Narrator', true, 'omnivoice'
FROM books
WHERE title = 'Provider Standalone';

INSERT INTO audiobook_characters (book_id, name, is_narrator, tts_voice_provider)
SELECT id, voice.name, voice.is_narrator, voice.provider
FROM books
CROSS JOIN (
    VALUES
        ('Narrator', true, 'qwen3'),
        ('Guest', false, 'omnivoice')
) AS voice(name, is_narrator, provider)
WHERE books.title = 'Provider Mixed History';

INSERT INTO audiobook_characters (book_id, name, is_narrator, tts_voice_provider)
SELECT id, 'Narrator', true, 'qwen3'
FROM books
WHERE title = 'Provider Deleted History';
