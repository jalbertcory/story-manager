DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'books'
          AND column_name = 'audiobook_tts_provider'
    ) THEN
        RAISE EXCEPTION '0038 provider lock column survived downgrade';
    END IF;

    IF (SELECT COUNT(*) FROM books WHERE title LIKE 'Provider %') <> 6 THEN
        RAISE EXCEPTION '0038 downgrade removed existing books';
    END IF;

    IF (
        SELECT COUNT(*)
        FROM audiobook_characters
        JOIN books ON books.id = audiobook_characters.book_id
        WHERE books.title LIKE 'Provider %'
    ) <> 5 THEN
        RAISE EXCEPTION '0038 downgrade removed existing characters';
    END IF;
END $$;
