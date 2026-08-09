UPDATE books
SET download_status = 'complete',
    refresh_status = 'unknown-refresh',
    audiobook_pipeline_status = 'unknown-pipeline',
    audiobook_publication_state = 'unknown-publication'
WHERE title = 'Migration Test';

UPDATE audiobook_chapters
SET preview_status = 'unknown-preview',
    generation_state = 'unknown-generation'
WHERE content_file_name = 'Text/existing.xhtml';

UPDATE audiobook_sentences
SET status = 'unknown-sentence'
WHERE html_element_id = 'existing-sentence';

UPDATE imported_audiobooks
SET status = 'unknown-import',
    alignment_method = 'unknown-alignment'
WHERE name = 'Pre-existing imported edition';

INSERT INTO processing_jobs (job_type, status, resource_lane)
VALUES ('migration_lifecycle_test', 'unknown-job', 'maintenance');

INSERT INTO update_tasks (total_books, completed_books, status)
VALUES (1, 0, 'unknown-task');

INSERT INTO metadata_sync_jobs (trigger, status, total_books)
VALUES ('migration-test', 'unknown-metadata', 1);
