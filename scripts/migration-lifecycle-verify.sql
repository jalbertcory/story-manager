DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM books
        WHERE title = 'Migration Test'
          AND download_status IS NULL
          AND refresh_status = 'error'
          AND audiobook_pipeline_status = 'error'
          AND audiobook_publication_state = 'error'
          AND audiobook_publication_error IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'book lifecycle values were not normalized';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM audiobook_chapters
        WHERE content_file_name = 'Text/existing.xhtml'
          AND preview_status = 'error'
          AND preview_error IS NOT NULL
          AND generation_state = 'error'
    ) THEN
        RAISE EXCEPTION 'chapter lifecycle values were not normalized';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM audiobook_sentences WHERE html_element_id = 'existing-sentence' AND status = 'error')
       OR NOT EXISTS (SELECT 1 FROM imported_audiobooks WHERE name = 'Pre-existing imported edition' AND status = 'error' AND alignment_method IS NULL AND alignment_error IS NOT NULL)
       OR NOT EXISTS (SELECT 1 FROM processing_jobs WHERE job_type = 'migration_lifecycle_test' AND status = 'error')
       OR NOT EXISTS (SELECT 1 FROM update_tasks WHERE status = 'interrupted')
       OR NOT EXISTS (SELECT 1 FROM metadata_sync_jobs WHERE trigger = 'migration-test' AND status = 'failed') THEN
        RAISE EXCEPTION 'one or more lifecycle values were not normalized';
    END IF;

    IF (
        SELECT count(*)
        FROM pg_constraint
        WHERE contype = 'c'
          AND conname IN (
                 'ck_books_download_status',
                 'ck_books_refresh_status',
                 'ck_books_audiobook_pipeline_status',
                 'ck_books_audiobook_publication_state',
                 'ck_processing_jobs_status',
                 'ck_update_tasks_status',
                 'ck_metadata_sync_jobs_status',
                 'ck_audiobook_chapters_preview_status',
                 'ck_audiobook_chapters_generation_state',
                 'ck_audiobook_sentences_status',
                 'ck_imported_audiobooks_status',
                 'ck_imported_audiobooks_alignment_method'
             )
    ) < 12 THEN
        RAISE EXCEPTION 'expected lifecycle check constraints were not created';
    END IF;

    BEGIN
        UPDATE books SET refresh_status = 'still-invalid' WHERE title = 'Migration Test';
        RAISE EXCEPTION 'invalid lifecycle value unexpectedly satisfied the check constraint';
    EXCEPTION
        WHEN check_violation THEN NULL;
    END;
END $$;
