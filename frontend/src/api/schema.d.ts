// Generated from FastAPI. Run npm run api:generate; do not edit.
export interface paths {
    "/api/audiobook/characters/{char_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Character */
        put: operations["update_character_api_audiobook_characters__char_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/characters/{char_id}/design-voice": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Design Character Voice */
        post: operations["design_character_voice_api_audiobook_characters__char_id__design_voice_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/characters/{char_id}/voice-sample": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Character Voice Sample */
        get: operations["get_character_voice_sample_api_audiobook_characters__char_id__voice_sample_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/imports/rebuild-all": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Rebuild All Human Audiobooks
         * @description Queue ready editions that are behind the current rebuild pipeline.
         */
        post: operations["rebuild_all_human_audiobooks_api_audiobook_imports_rebuild_all_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/imports/rebuild-preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Preview Human Audiobook Rebuilds
         * @description Summarize editions that need the current human-audiobook pipeline.
         */
        get: operations["preview_human_audiobook_rebuilds_api_audiobook_imports_rebuild_preview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/imports/upgrade-all": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Upgrade All Imported Audiobooks
         * @description Queue every ready human audiobook that has rebuildable legacy assets.
         */
        post: operations["upgrade_all_imported_audiobooks_api_audiobook_imports_upgrade_all_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/libation-backup/preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Preview Libation Backup
         * @description Match a path-only Libation backup manifest before any audio is uploaded.
         */
        post: operations["preview_libation_backup_api_audiobook_libation_backup_preview_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/sentences/{sentence_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Sentence */
        put: operations["update_sentence_api_audiobook_sentences__sentence_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/sentences/{sentence_id}/audio": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Sentence Audio */
        get: operations["get_sentence_audio_api_audiobook_sentences__sentence_id__audio_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Settings */
        get: operations["get_settings_api_audiobook_settings_get"];
        /** Update Settings */
        put: operations["update_settings_api_audiobook_settings_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/settings/endpoint-stats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Endpoint Stats
         * @description Compare reliability and response latency across all configured AI endpoints.
         */
        get: operations["get_endpoint_stats_api_audiobook_settings_endpoint_stats_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/settings/llm-stats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Llm Endpoint Stats
         * @description Compare reliability and response latency across configured LLM endpoints.
         */
        get: operations["get_llm_endpoint_stats_api_audiobook_settings_llm_stats_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/settings/test-llm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Test Llm Settings */
        post: operations["test_llm_settings_api_audiobook_settings_test_llm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/settings/test-transcription": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Test Transcription Settings */
        post: operations["test_transcription_settings_api_audiobook_settings_test_transcription_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobook/settings/test-tts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Test Tts Settings */
        post: operations["test_tts_settings_api_audiobook_settings_test_tts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audiobooks/upload": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Upload Audio Only Book */
        post: operations["upload_audio_only_book_api_audiobooks_upload_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Login */
        post: operations["login_api_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Logout */
        post: operations["logout_api_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Auth Status */
        get: operations["auth_status_api_auth_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/backups": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Backups */
        get: operations["get_backups_api_backups_get"];
        put?: never;
        /** Create Backup */
        post: operations["create_backup_api_backups_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/backups/{filename}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Backup */
        delete: operations["delete_backup_api_backups__filename__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/backups/{filename}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Download Backup */
        get: operations["download_backup_api_backups__filename__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/backups/{filename}/verify": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Verify Backup */
        post: operations["verify_backup_api_backups__filename__verify_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get All Books */
        get: operations["get_all_books_api_books_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Book */
        get: operations["get_book_api_books__book_id__get"];
        /** Update Book Details */
        put: operations["update_book_details_api_books__book_id__put"];
        post?: never;
        /** Delete Book By Id */
        delete: operations["delete_book_by_id_api_books__book_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/audio/rebuild": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Rebuild Audio Only
         * @description Regenerate AI TTS and assembly without changing speaker analysis.
         */
        post: operations["rebuild_audio_only_api_books__book_id__audiobook_audio_rebuild_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/chapters": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Chapters */
        get: operations["list_chapters_api_books__book_id__audiobook_chapters_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/chapters/{chapter_id}/audio": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Chapter Audio */
        get: operations["get_chapter_audio_api_books__book_id__audiobook_chapters__chapter_id__audio_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/chapters/{chapter_id}/preview-audio": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Generate Chapter Preview */
        post: operations["generate_chapter_preview_api_books__book_id__audiobook_chapters__chapter_id__preview_audio_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/characters": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Characters */
        get: operations["list_characters_api_books__book_id__audiobook_characters_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Download Audiobook */
        get: operations["download_audiobook_api_books__book_id__audiobook_download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/imports": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Imported Audiobooks */
        get: operations["list_imported_audiobooks_api_books__book_id__audiobook_imports_get"];
        put?: never;
        /** Upload Imported Audiobook */
        post: operations["upload_imported_audiobook_api_books__book_id__audiobook_imports_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/pause": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Pause Pipeline */
        post: operations["pause_pipeline_api_books__book_id__audiobook_pause_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/rebuild": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Rebuild Pipeline */
        post: operations["rebuild_pipeline_api_books__book_id__audiobook_rebuild_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/roster/rebuild": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Rebuild Character Roster
         * @description Re-run roster and diarization analysis without parsing the EPUB again.
         */
        post: operations["rebuild_character_roster_api_books__book_id__audiobook_roster_rebuild_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/roster/share-series": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Share Character Roster With Series */
        post: operations["share_character_roster_with_series_api_books__book_id__audiobook_roster_share_series_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/run-batch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Run Pipeline Batch
         * @description Run one durable LLM/TTS/assembly work unit, then pause for review.
         */
        post: operations["run_pipeline_batch_api_books__book_id__audiobook_run_batch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/sentences": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Sentences */
        get: operations["list_sentences_api_books__book_id__audiobook_sentences_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/sentences/{sentence_id}/generate-audio": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Generate Sentence Audio */
        post: operations["generate_sentence_audio_api_books__book_id__audiobook_sentences__sentence_id__generate_audio_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start Pipeline */
        post: operations["start_pipeline_api_books__book_id__audiobook_start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Pipeline Status */
        get: operations["get_pipeline_status_api_books__book_id__audiobook_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/step": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Step Pipeline
         * @description Run exactly the next recoverable phase, then stop for review.
         */
        post: operations["step_pipeline_api_books__book_id__audiobook_step_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/audiobook/tts-provider": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Book Tts Provider */
        put: operations["update_book_tts_provider_api_books__book_id__audiobook_tts_provider_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/chapters": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Book Chapters */
        get: operations["get_book_chapters_api_books__book_id__chapters_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/cleaned-chapters": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Book Cleaned Chapters */
        get: operations["get_book_cleaned_chapters_api_books__book_id__cleaned_chapters_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/cover": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Upload Book Cover */
        post: operations["upload_book_cover_api_books__book_id__cover_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/cover-url": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Set Cover From Url
         * @description Downloads an image from a URL and sets it as the book's cover.
         */
        post: operations["set_cover_from_url_api_books__book_id__cover_url_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/detach-source": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Detach Book Source
         * @description Remove a book's web/source URL metadata and treat it as a normal EPUB.
         */
        post: operations["detach_book_source_api_books__book_id__detach_source_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Download Book */
        get: operations["download_book_api_books__book_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/matched-config": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Book Matched Config
         * @description Returns all CleaningConfigs that match the book's source URL.
         */
        get: operations["get_book_matched_config_api_books__book_id__matched_config_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/preview-cleaning": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Preview Cleaning */
        post: operations["preview_cleaning_api_books__book_id__preview_cleaning_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/process": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Process Book Endpoint */
        post: operations["process_book_endpoint_api_books__book_id__process_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Refresh Book
         * @description Queue a background refresh of a web novel from its source URL.
         *
         *     Returns 202 Accepted immediately with the book's updated ``refresh_status``.
         *     Clients should poll ``GET /api/books/{book_id}`` until ``refresh_status`` is
         *     null (success) or ``"error"``. The actual work — re-downloading via
         *     FanFicFare, rebuilding the cleaned EPUB, re-syncing metadata — runs as a
         *     durable processing job in the same flow used by the scheduled update.
         */
        post: operations["refresh_book_api_books__book_id__refresh_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/restore-original": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Restore Original Epub */
        post: operations["restore_original_epub_api_books__book_id__restore_original_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/retry-cover": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Retry Cover
         * @description Queue cover extraction from the EPUB with source scraping as fallback.
         */
        post: operations["retry_cover_api_books__book_id__retry_cover_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/revisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Book Revisions */
        get: operations["list_book_revisions_api_books__book_id__revisions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/revisions/{revision_id}/restore": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Restore Book Revision */
        post: operations["restore_book_revision_api_books__book_id__revisions__revision_id__restore_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/{book_id}/update-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Book Update History */
        get: operations["get_book_update_history_api_books__book_id__update_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/add_web_novel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Add Web Novel
         * @description Creates a pending book record immediately and queues the download.
         */
        post: operations["add_web_novel_api_books_add_web_novel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/by-title/{title}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Book By Title */
        delete: operations["delete_book_by_title_api_books_by_title__title__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/catalog": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Book Catalog */
        get: operations["get_book_catalog_api_books_catalog_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/count": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Count Books Endpoint */
        get: operations["count_books_endpoint_api_books_count_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/details": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Book Details */
        get: operations["get_book_details_api_books_details_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/detect-series": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Detect Series In Library
         * @description Scans all books without an assigned series and auto-detects groupings
         *     using title patterns like "<series> <number> [- <subtitle>]".
         */
        post: operations["detect_series_in_library_api_books_detect_series_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/remove-all": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Remove All Books */
        post: operations["remove_all_books_api_books_remove_all_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/reprocess-all": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reprocess All Books */
        post: operations["reprocess_all_books_api_books_reprocess_all_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/reprocess-all/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reprocess All Status */
        get: operations["reprocess_all_status_api_books_reprocess_all_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Search Books Unified */
        get: operations["search_books_unified_api_books_search_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/search/author/{author}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Search Books By Author */
        get: operations["search_books_by_author_api_books_search_author__author__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/search/series/{series}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Search Books By Series */
        get: operations["search_books_by_series_api_books_search_series__series__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/upload_epub": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Upload Epub
         * @description Uploads a single EPUB file, extracts metadata, and adds it to the database.
         */
        post: operations["upload_epub_api_books_upload_epub_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/books/upload_epubs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Upload Epubs
         * @description Uploads multiple EPUB files. After processing all files, auto-detects series groupings
         *     among books with no series metadata using the pattern "<series name> <number> [- <subtitle>]".
         */
        post: operations["upload_epubs_api_books_upload_epubs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/cleaning-configs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Cleaning Configs */
        get: operations["list_cleaning_configs_api_cleaning_configs_get"];
        put?: never;
        /** Create Cleaning Config Endpoint */
        post: operations["create_cleaning_config_endpoint_api_cleaning_configs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/cleaning-configs/{config_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Cleaning Config Endpoint */
        get: operations["get_cleaning_config_endpoint_api_cleaning_configs__config_id__get"];
        /** Update Cleaning Config Endpoint */
        put: operations["update_cleaning_config_endpoint_api_cleaning_configs__config_id__put"];
        post?: never;
        /** Delete Cleaning Config Endpoint */
        delete: operations["delete_cleaning_config_endpoint_api_cleaning_configs__config_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/covers/{book_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Cover Image
         * @description Serves the cover image for a given book ID.
         */
        get: operations["get_cover_image_api_covers__book_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/dashboard/attention": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Attention Dashboard */
        get: operations["get_attention_dashboard_api_dashboard_attention_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/imported-audiobooks/{edition_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Imported Audiobook */
        delete: operations["delete_imported_audiobook_api_imported_audiobooks__edition_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/imported-audiobooks/{edition_id}/align": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Align Imported Audiobook */
        post: operations["align_imported_audiobook_api_imported_audiobooks__edition_id__align_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/imported-audiobooks/{edition_id}/rematch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Rematch Imported Audiobook
         * @description Rebuild human-audio chapter matches and text cues without reimporting audio.
         */
        post: operations["rematch_imported_audiobook_api_imported_audiobooks__edition_id__rematch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/imported-audiobooks/{edition_id}/retry": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retry Imported Audiobook */
        post: operations["retry_imported_audiobook_api_imported_audiobooks__edition_id__retry_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/imported-audiobooks/{edition_id}/tracks/{track_id}/audio": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Imported Track Audio */
        get: operations["get_imported_track_audio_api_imported_audiobooks__edition_id__tracks__track_id__audio_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/imported-audiobooks/{edition_id}/tracks/{track_id}/cues": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Imported Track Cues */
        get: operations["get_imported_track_cues_api_imported_audiobooks__edition_id__tracks__track_id__cues_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/imported-audiobooks/{edition_id}/tracks/{track_id}/match": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Match Imported Track */
        put: operations["match_imported_track_api_imported_audiobooks__edition_id__tracks__track_id__match_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/imported-audiobooks/{edition_id}/tracks/{track_id}/smil": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Imported Track Smil */
        get: operations["get_imported_track_smil_api_imported_audiobooks__edition_id__tracks__track_id__smil_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/imported-audiobooks/{edition_id}/upgrade": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Upgrade Imported Audiobook
         * @description Rebuild derived chapter audio from the retained immutable source files.
         */
        post: operations["upgrade_imported_audiobook_api_imported_audiobooks__edition_id__upgrade_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/imports/preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Preview Imports
         * @description Inspect book files and web URLs without creating records or queueing work.
         */
        post: operations["preview_imports_api_imports_preview_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/library/books/{book_id}/info": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Book Info */
        get: operations["book_info_api_library_books__book_id__info_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/library/groups": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Groups */
        get: operations["groups_api_library_groups_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/library/universe-membership": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Set Membership */
        put: operations["set_membership_api_library_universe_membership_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/library/universes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Universes */
        get: operations["universes_api_library_universes_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/library/validate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Validate Library
         * @description Check every book record for missing or broken file paths.
         *     Returns a list of issues found (empty list means everything is healthy).
         */
        get: operations["validate_library_api_library_validate_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/library/web-checks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Web Checks */
        get: operations["web_checks_api_library_web_checks_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/lifecycles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Lifecycle Definitions */
        get: operations["get_lifecycle_definitions_api_lifecycles_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/logs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Logs */
        get: operations["get_logs_api_logs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/logs/client": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Post Client Log
         * @description Receive log entries from the frontend UI.
         */
        post: operations["post_client_log_api_logs_client_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/metadata/apply": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Sync Metadata Apply */
        post: operations["sync_metadata_apply_api_metadata_apply_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/metadata/inbox": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Metadata Inbox */
        get: operations["get_metadata_inbox_api_metadata_inbox_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/metadata/jobs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Metadata Job */
        post: operations["create_metadata_job_api_metadata_jobs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/metadata/jobs/latest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Latest Metadata Job */
        get: operations["get_latest_metadata_job_api_metadata_jobs_latest_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/metadata/matches/{match_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Approve Match */
        post: operations["approve_match_api_metadata_matches__match_id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/metadata/matches/{match_id}/reject": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reject Match */
        post: operations["reject_match_api_metadata_matches__match_id__reject_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/metadata/proposals/{proposal_id}/dismiss": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Dismiss Proposal */
        post: operations["dismiss_proposal_api_metadata_proposals__proposal_id__dismiss_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/metadata/sync-preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Sync Metadata Preview */
        post: operations["sync_metadata_preview_api_metadata_sync_preview_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/observability/diagnostics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Download Diagnostics
         * @description Download a redacted bundle with no library files, audio, or secret configuration.
         */
        get: operations["download_diagnostics_api_observability_diagnostics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/observability/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Health */
        get: operations["get_health_api_observability_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/observability/job-metrics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Job Metrics */
        get: operations["get_job_metrics_api_observability_job_metrics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/observability/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Readiness */
        get: operations["get_readiness_api_observability_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/processing/jobs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Processing Jobs */
        get: operations["list_processing_jobs_api_processing_jobs_get"];
        put?: never;
        /** Create Processing Jobs */
        post: operations["create_processing_jobs_api_processing_jobs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/processing/jobs/{job_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Processing Job */
        get: operations["get_processing_job_api_processing_jobs__job_id__get"];
        put?: never;
        post?: never;
        /** Cancel Processing Job */
        delete: operations["cancel_processing_job_api_processing_jobs__job_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/processing/jobs/{job_id}/retry": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retry Processing Job */
        post: operations["retry_processing_job_api_processing_jobs__job_id__retry_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/reader-keys": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Reader Keys */
        get: operations["list_reader_keys_api_reader_keys_get"];
        put?: never;
        /** Create Reader Key */
        post: operations["create_reader_key_api_reader_keys_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/reader-keys/{key_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Revoke Reader Key */
        delete: operations["revoke_reader_key_api_reader_keys__key_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/recycle-bin": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Recycle Bin */
        get: operations["get_recycle_bin_api_recycle_bin_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/recycle-bin/{book_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Permanently Delete Recycled Book */
        delete: operations["permanently_delete_recycled_book_api_recycle_bin__book_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/recycle-bin/{book_id}/restore": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Restore Recycled Book */
        post: operations["restore_recycled_book_api_recycle_bin__book_id__restore_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/recycle-bin/purge-expired": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Purge Expired Recycled Books */
        post: operations["purge_expired_recycled_books_api_recycle_bin_purge_expired_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scheduler/config": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Scheduler Config */
        put: operations["update_scheduler_config_api_scheduler_config_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scheduler/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Scheduler History */
        get: operations["get_scheduler_history_api_scheduler_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scheduler/history/{task_id}/logs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Task Logs */
        get: operations["get_task_logs_api_scheduler_history__task_id__logs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scheduler/job": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Scheduler Job Status */
        get: operations["get_scheduler_job_status_api_scheduler_job_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scheduler/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Scheduler Status */
        get: operations["get_scheduler_status_api_scheduler_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scheduler/trigger": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Trigger Scheduler */
        post: operations["trigger_scheduler_api_scheduler_trigger_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/series": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Series
         * @description Return all distinct series names in the library, sorted alphabetically.
         */
        get: operations["list_series_api_series_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/series/{series_name}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Rename Series
         * @description Rename a series, updating all books that belong to it.
         */
        put: operations["rename_series_api_series__series_name__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/series/{series_name}/genres": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Series Genres */
        get: operations["get_series_genres_api_series__series_name__genres_get"];
        /** Update Series Genres */
        put: operations["update_series_genres_api_series__series_name__genres_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/series/{series_name}/reorder": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reorder Series
         * @description Persist the order of every book in a series.
         */
        post: operations["reorder_series_api_series__series_name__reorder_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/series/merge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Merge Series
         * @description Merge source series into target series.
         */
        post: operations["merge_series_api_series_merge_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/storage/cleanup": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Cleanup Storage
         * @description Scans the library directory for files not referenced by any book record and
         *     failed web-import placeholder books that never produced EPUB files.
         *     dry_run=True (default): returns what would be deleted without deleting.
         *     dry_run=False: deletes orphaned files and failed placeholder books.
         */
        post: operations["cleanup_storage_api_storage_cleanup_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health Check
         * @description Health check endpoint for container orchestration.
         */
        get: operations["health_check_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/live": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Liveness Check
         * @description Process-only health check that never depends on external services.
         */
        get: operations["liveness_check_health_live_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Readiness Check
         * @description Required-dependency readiness check for container orchestration.
         */
        get: operations["readiness_check_health_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/books/{book_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Reader Book */
        get: operations["get_reader_book_reader_books__book_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/books/{book_id}/audiobook/chapters/{chapter_key}/audio": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reader Audiobook Chapter Audio */
        get: operations["reader_audiobook_chapter_audio_reader_books__book_id__audiobook_chapters__chapter_key__audio_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/books/{book_id}/audiobook/chapters/{chapter_key}/smil": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reader Audiobook Chapter Smil */
        get: operations["reader_audiobook_chapter_smil_reader_books__book_id__audiobook_chapters__chapter_key__smil_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/books/{book_id}/audiobook/manifest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reader Audiobook Manifest */
        get: operations["reader_audiobook_manifest_reader_books__book_id__audiobook_manifest_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/books/{book_id}/audiobook/text": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reader Audiobook Text */
        get: operations["reader_audiobook_text_reader_books__book_id__audiobook_text_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/books/{book_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reader Download Book */
        get: operations["reader_download_book_reader_books__book_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/books/{book_id}/human-audiobooks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Reader Human Audiobooks
         * @description Reader-key-safe metadata for ready human-narrated audiobook editions.
         */
        get: operations["get_reader_human_audiobooks_reader_books__book_id__human_audiobooks_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/books/{book_id}/human-audiobooks/chapters": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Reader Human Audiobook Chapters
         * @description Chapter ids and hrefs used to match imported tracks to publication resources.
         */
        get: operations["get_reader_human_audiobook_chapters_reader_books__book_id__human_audiobooks_chapters_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/books/all": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get All Reader Books */
        get: operations["get_all_reader_books_reader_books_all_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/books/standalone": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Reader Standalone Books */
        get: operations["get_reader_standalone_books_reader_books_standalone_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/covers/{book_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reader Cover */
        get: operations["reader_cover_reader_covers__book_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/human-audiobooks/{edition_id}/tracks/{track_id}/audio": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Reader Human Audiobook Audio */
        get: operations["get_reader_human_audiobook_audio_reader_human_audiobooks__edition_id__tracks__track_id__audio_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/human-audiobooks/{edition_id}/tracks/{track_id}/smil": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Reader Human Audiobook Smil */
        get: operations["get_reader_human_audiobook_smil_reader_human_audiobooks__edition_id__tracks__track_id__smil_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/opds": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reader Opds Root */
        get: operations["reader_opds_root_reader_opds_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/opds/catalog": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reader Opds Catalog */
        get: operations["reader_opds_catalog_reader_opds_catalog_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/opds/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reader Opds Search */
        get: operations["reader_opds_search_reader_opds_search_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/opds/series": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reader Opds Series */
        get: operations["reader_opds_series_reader_opds_series_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/opds/series/{series_name}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reader Opds Series Books */
        get: operations["reader_opds_series_books_reader_opds_series__series_name__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/series": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Reader Series */
        get: operations["get_reader_series_reader_series_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/series/{series_name}/books": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Reader Series Books */
        get: operations["get_reader_series_books_reader_series__series_name__books_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/reader/updates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Reader Updates */
        get: operations["get_reader_updates_reader_updates_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AdminAuthStatus */
        AdminAuthStatus: {
            /** Authenticated */
            authenticated: boolean;
            /** Mode */
            mode: string;
        };
        /** AdminLoginRequest */
        AdminLoginRequest: {
            /** Password */
            password: string;
        };
        /** AllEndpointStatsResponse */
        AllEndpointStatsResponse: {
            /** Llm */
            llm: components["schemas"]["EndpointStats"][];
            /** Transcription */
            transcription: components["schemas"]["EndpointStats"][];
            /** Tts */
            tts: components["schemas"]["EndpointStats"][];
        };
        /** ApiKey */
        ApiKey: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Id */
            id: number;
            /** Label */
            label: string;
            /** Last Used At */
            last_used_at: string | null;
            /** Revoked At */
            revoked_at: string | null;
            /** Token Prefix */
            token_prefix: string;
        };
        /** ApiKeyCreate */
        ApiKeyCreate: {
            /** Label */
            label: string;
        };
        /** ApiKeyWithToken */
        ApiKeyWithToken: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Id */
            id: number;
            /** Label */
            label: string;
            /** Last Used At */
            last_used_at: string | null;
            /** Revoked At */
            revoked_at: string | null;
            /** Token */
            token: string;
            /** Token Prefix */
            token_prefix: string;
        };
        /** AttentionBookCategory */
        AttentionBookCategory: {
            /** Count */
            count: number;
            /** Items */
            items: components["schemas"]["AttentionBookItem"][];
        };
        /** AttentionBookItem */
        AttentionBookItem: {
            /** Author */
            author: string;
            /** Book Id */
            book_id: number;
            /**
             * Can Retry Refresh
             * @default false
             */
            can_retry_refresh: boolean;
            /** Detail */
            detail: string | null;
            /** Issue */
            issue: string;
            /** Title */
            title: string;
        };
        /** AttentionDashboard */
        AttentionDashboard: {
            broken_files: components["schemas"]["AttentionFileCategory"];
            failed_jobs: components["schemas"]["AttentionJobCategory"];
            failed_refreshes: components["schemas"]["AttentionBookCategory"];
            metadata_proposals: components["schemas"]["AttentionMetadataCategory"];
            missing_covers: components["schemas"]["AttentionFileCategory"];
            stale_audiobooks: components["schemas"]["AttentionBookCategory"];
            /** Total Count */
            total_count: number;
        };
        /** AttentionFileCategory */
        AttentionFileCategory: {
            /** Count */
            count: number;
            /** Items */
            items: components["schemas"]["AttentionFileItem"][];
        };
        /** AttentionFileItem */
        AttentionFileItem: {
            /** Author */
            author: string;
            /** Book Id */
            book_id: number;
            /**
             * Can Retry Cover
             * @default false
             */
            can_retry_cover: boolean;
            /**
             * Can Retry Refresh
             * @default false
             */
            can_retry_refresh: boolean;
            /** Detail */
            detail: string | null;
            /** Issue */
            issue: string;
            /** Path */
            path: string | null;
            /** Title */
            title: string;
        };
        /** AttentionJobCategory */
        AttentionJobCategory: {
            /** Count */
            count: number;
            /** Items */
            items: components["schemas"]["AttentionJobItem"][];
        };
        /** AttentionJobItem */
        AttentionJobItem: {
            /** Book Id */
            book_id: number | null;
            /** Book Title */
            book_title: string | null;
            /** Completed At */
            completed_at: string | null;
            /** Error */
            error: string | null;
            /** Id */
            id: number;
            /** Job Type */
            job_type: string;
        };
        /** AttentionMetadataCategory */
        AttentionMetadataCategory: {
            /** Count */
            count: number;
            /** Items */
            items: components["schemas"]["AttentionMetadataItem"][];
        };
        /** AttentionMetadataItem */
        AttentionMetadataItem: {
            /** Author */
            author: string;
            /** Book Id */
            book_id: number;
            /** Note */
            note: string | null;
            /** Proposal Id */
            proposal_id: number;
            /** Title */
            title: string;
        };
        /** AudiobookStatusResponse */
        AudiobookStatusResponse: {
            /** Available Tts Providers */
            available_tts_providers: string[];
            /** Batch Limit */
            batch_limit: number | null;
            /** Last Error */
            last_error: string | null;
            /** Llm Model */
            llm_model: string | null;
            /** Llm Provider */
            llm_provider: string;
            /** Llm Requests */
            llm_requests: number;
            /** Next Phase */
            next_phase: string;
            /** Pause Requested */
            pause_requested: boolean;
            /** Pipeline Started At */
            pipeline_started_at: string | null;
            /** Pipeline Status */
            pipeline_status: string | null;
            /** Pipeline Updated At */
            pipeline_updated_at: string | null;
            /** Progress Current */
            progress_current: number;
            /** Progress Detail */
            progress_detail: string | null;
            /** Progress Percent */
            progress_percent: number | null;
            /** Progress Total */
            progress_total: number;
            /** Review Counts */
            review_counts: {
                [key: string]: number;
            };
            /** Sentence Counts */
            sentence_counts: {
                [key: string]: number;
            };
            /** Stop After Phase */
            stop_after_phase: string | null;
            /** Summary */
            summary: string | null;
            /** Tts Model */
            tts_model: string | null;
            /** Tts Provider */
            tts_provider: string;
            /** Tts Provider Locked */
            tts_provider_locked: boolean;
        };
        /** BackupArchive */
        BackupArchive: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Download Url */
            download_url: string;
            /** Error */
            error: string | null;
            /** Filename */
            filename: string;
            /** Library File Count */
            library_file_count: number;
            /** Library Size Bytes */
            library_size_bytes: number;
            /** Size Bytes */
            size_bytes: number;
            /** Valid Manifest */
            valid_manifest: boolean;
            /** Verified At Creation */
            verified_at_creation: boolean;
        };
        /** BackupInventory */
        BackupInventory: {
            /** Backups */
            backups: components["schemas"]["BackupArchive"][];
            /** Retention Count */
            retention_count: number;
        };
        /** Body_preview_imports_api_imports_preview_post */
        Body_preview_imports_api_imports_preview_post: {
            /**
             * Files
             * @default []
             */
            files: Blob[];
            /**
             * Urls
             * @default []
             */
            urls: string[];
        };
        /** Body_upload_audio_only_book_api_audiobooks_upload_post */
        Body_upload_audio_only_book_api_audiobooks_upload_post: {
            /**
             * Author
             * @default Unknown author
             */
            author: string;
            /** Files */
            files: Blob[];
            /**
             * Infer Title
             * @default false
             */
            infer_title: boolean;
            /** Name */
            name?: string | null;
            /**
             * Source Paths
             * @default []
             */
            source_paths: string[];
            /**
             * Title
             * @default
             */
            title: string;
        };
        /** Body_upload_book_cover_api_books__book_id__cover_post */
        Body_upload_book_cover_api_books__book_id__cover_post: {
            /** File */
            file: Blob;
        };
        /** Body_upload_epub_api_books_upload_epub_post */
        Body_upload_epub_api_books_upload_epub_post: {
            /** File */
            file: Blob;
        };
        /** Body_upload_epubs_api_books_upload_epubs_post */
        Body_upload_epubs_api_books_upload_epubs_post: {
            /** Files */
            files: Blob[];
        };
        /** Body_upload_imported_audiobook_api_books__book_id__audiobook_imports_post */
        Body_upload_imported_audiobook_api_books__book_id__audiobook_imports_post: {
            /**
             * Auto Align
             * @default true
             */
            auto_align: boolean;
            /** Files */
            files: Blob[];
            /** Name */
            name?: string | null;
            /**
             * Source Paths
             * @default []
             */
            source_paths: string[];
        };
        /** Book */
        Book: {
            /**
             * Audiobook Enabled
             * @default false
             */
            audiobook_enabled: boolean;
            /** Audiobook Pipeline Status */
            audiobook_pipeline_status: string | null;
            /** Audiobook Tts Provider */
            audiobook_tts_provider: string | null;
            /** Author */
            author: string;
            /** Content Selectors */
            content_selectors: string[] | null;
            /**
             * Content Updated At
             * Format: date-time
             */
            content_updated_at: string;
            /** Content Version */
            content_version: number;
            /** Cover Path */
            cover_path: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Current Path */
            current_path: string | null;
            /** Current Word Count */
            current_word_count: number | null;
            /** Deleted At */
            deleted_at: string | null;
            /** Download Status */
            download_status: string | null;
            /** Genre Tags */
            genre_tags: string[] | null;
            /** Id */
            id: number;
            /** Immutable Path */
            immutable_path: string | null;
            /** Master Word Count */
            master_word_count: number | null;
            /** Metadata Details */
            metadata_details: {
                [key: string]: unknown;
            } | null;
            /** Metadata Remote Ids */
            metadata_remote_ids: {
                [key: string]: unknown;
            } | null;
            /** Metadata Sync Source */
            metadata_sync_source: string | null;
            /** Metadata Synced At */
            metadata_synced_at: string | null;
            /** Notes */
            notes: string | null;
            /** Purge After */
            purge_after: string | null;
            /** Refresh Status */
            refresh_status: string | null;
            /** Removed Chapters */
            removed_chapters: string[] | null;
            /** Series */
            series: string | null;
            /** Series Index */
            series_index: number | null;
            /** Source Tags */
            source_tags: string[] | null;
            source_type: components["schemas"]["SourceType"];
            /** Source Url */
            source_url: string | null;
            /** Title */
            title: string;
            /** Updated At */
            updated_at: string | null;
            /** User Genre Tags */
            user_genre_tags: string[] | null;
        };
        /** BookCatalogEntry */
        BookCatalogEntry: {
            /**
             * Audio Playable
             * @default false
             */
            audio_playable: boolean;
            /**
             * Audiobook Enabled
             * @default false
             */
            audiobook_enabled: boolean;
            /** Audiobook Pipeline Status */
            audiobook_pipeline_status: string | null;
            /** Audiobook Types */
            audiobook_types: ("ai_generated" | "human_narrated")[];
            /** Author */
            author: string;
            /** Cover Path */
            cover_path: string | null;
            /** Current Word Count */
            current_word_count: number | null;
            /** Download Status */
            download_status: string | null;
            /** Effective Genre Tags */
            effective_genre_tags: string[] | null;
            /** Effective Series Genre Tags */
            effective_series_genre_tags: string[] | null;
            /** Genre Tags */
            genre_tags: string[] | null;
            /**
             * Has Epub
             * @default false
             */
            has_epub: boolean;
            /** Id */
            id: number;
            /** Refresh Status */
            refresh_status: string | null;
            /** Series */
            series: string | null;
            /** Series Index */
            series_index: number | null;
            /** Series User Genre Tags */
            series_user_genre_tags: string[] | null;
            source_type: components["schemas"]["SourceType"];
            /** Source Url */
            source_url: string | null;
            /** Title */
            title: string;
            /** Universe Id */
            universe_id: number | null;
            /** Universe Name */
            universe_name: string | null;
            /** Updated At */
            updated_at: string | null;
            /** User Genre Tags */
            user_genre_tags: string[] | null;
        };
        /** BookCatalogFacets */
        BookCatalogFacets: {
            /**
             * Audiobook Available
             * @default 0
             */
            audiobook_available: number;
            /**
             * Audiobook Missing
             * @default 0
             */
            audiobook_missing: number;
            /** Genres */
            genres: components["schemas"]["CatalogGenreFacet"][];
            /**
             * Missing Series
             * @default 0
             */
            missing_series: number;
            /**
             * Refresh Attention
             * @default 0
             */
            refresh_attention: number;
            /**
             * Refreshing
             * @default 0
             */
            refreshing: number;
            /**
             * Series
             * @default 0
             */
            series: number;
            /**
             * Standalone
             * @default 0
             */
            standalone: number;
            /**
             * Web
             * @default 0
             */
            web: number;
        };
        /** BookCatalogPage */
        BookCatalogPage: {
            facets: components["schemas"]["BookCatalogFacets"];
            /** Items */
            items: components["schemas"]["BookCatalogEntry"][];
            /** Next Cursor */
            next_cursor: string | null;
            /**
             * Total Count
             * @default 0
             */
            total_count: number;
        };
        /** BookChapterUpdateHistory */
        BookChapterUpdateHistory: {
            /** Book Id */
            book_id: number;
            /** History */
            history: components["schemas"]["BookChapterUpdateHistoryPoint"][];
            summary: components["schemas"]["BookChapterUpdateHistorySummary"];
        };
        /** BookChapterUpdateHistoryPoint */
        BookChapterUpdateHistoryPoint: {
            /** Average Words Per Chapter */
            average_words_per_chapter: number | null;
            /** Chapters Added */
            chapters_added: number;
            /** Entry Type */
            entry_type: string;
            /** Id */
            id: number;
            /**
             * Included In Stats
             * @default false
             */
            included_in_stats: boolean;
            /**
             * Is Catch Up Sync
             * @default false
             */
            is_catch_up_sync: boolean;
            /**
             * Is Initial Sync
             * @default false
             */
            is_initial_sync: boolean;
            /** New Chapter Count */
            new_chapter_count: number | null;
            /** Previous Chapter Count */
            previous_chapter_count: number | null;
            /**
             * Timestamp
             * Format: date-time
             */
            timestamp: string;
            /** Words Added */
            words_added: number;
        };
        /** BookChapterUpdateHistorySummary */
        BookChapterUpdateHistorySummary: {
            /** Average Days Between Updates */
            average_days_between_updates: number | null;
            /** Average Words Per Month */
            average_words_per_month: number | null;
            /** Average Words Per Week */
            average_words_per_week: number | null;
            /** Last Update At */
            last_update_at: string | null;
            /** Predicted Next Update At */
            predicted_next_update_at: string | null;
            /** Total Chapters Added */
            total_chapters_added: number;
            /** Total Update Events */
            total_update_events: number;
            /** Total Words Added */
            total_words_added: number;
        };
        /** BookCount */
        BookCount: {
            /** Total */
            total: number;
        };
        /** BookLogWithTitle */
        BookLogWithTitle: {
            /** Book Id */
            book_id: number;
            /** Book Title */
            book_title: string;
            /** Entry Type */
            entry_type: string;
            /** Id */
            id: number;
            /** New Chapter Count */
            new_chapter_count: number | null;
            /** Previous Chapter Count */
            previous_chapter_count: number | null;
            /**
             * Timestamp
             * Format: date-time
             */
            timestamp: string;
            /** Words Added */
            words_added: number | null;
        };
        /** BookRemovalPreview */
        BookRemovalPreview: {
            /** Author */
            author: string | null;
            /** Files */
            files: components["schemas"]["FileSize"][];
            /** Id */
            id: number;
            /** Log Entries */
            log_entries: number;
            /** Title */
            title: string | null;
        };
        /** BookRevision */
        BookRevision: {
            /** Action */
            action: string;
            /** Book Id */
            book_id: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Id */
            id: number;
            /** Snapshot */
            snapshot: {
                [key: string]: unknown;
            };
            /** Summary */
            summary: string;
        };
        /** BookTTSProviderUpdate */
        BookTTSProviderUpdate: {
            /** Provider */
            provider: string;
        };
        /** BookUpdate */
        BookUpdate: {
            /** Audiobook Enabled */
            audiobook_enabled?: boolean | null;
            /** Author */
            author?: string | null;
            /** Content Selectors */
            content_selectors?: string[] | null;
            /** Genre Tags */
            genre_tags?: string[] | null;
            /** Metadata Remote Ids */
            metadata_remote_ids?: {
                [key: string]: unknown;
            } | null;
            /** Notes */
            notes?: string | null;
            /** Removed Chapters */
            removed_chapters?: string[] | null;
            /** Series */
            series?: string | null;
            /** Series Index */
            series_index?: number | null;
            /** Source Tags */
            source_tags?: string[] | null;
            /** Title */
            title?: string | null;
            /** User Genre Tags */
            user_genre_tags?: string[] | null;
        };
        /** CatalogFacets */
        CatalogFacets: {
            /** Audiobook Available */
            audiobook_available: number;
            /** Audiobook Missing */
            audiobook_missing: number;
            /** Genres */
            genres: components["schemas"]["GenreFacet"][];
            /** Missing Series */
            missing_series: number;
            /** Refresh Attention */
            refresh_attention: number;
            /** Refreshing */
            refreshing: number;
            /** Series */
            series: number;
            /** Standalone */
            standalone: number;
            /** Web */
            web: number;
        };
        /** CatalogGenreFacet */
        CatalogGenreFacet: {
            /** Count */
            count: number;
            /** Name */
            name: string;
        };
        /** ChapterPreviewQueued */
        ChapterPreviewQueued: {
            /** Batch Limit */
            batch_limit?: number;
            /** Chapter Id */
            chapter_id?: number;
            /** Queued */
            queued: boolean;
            /** Status */
            status: string | null;
            /** Stop After Phase */
            stop_after_phase?: string;
        };
        /** ChapterResponse */
        ChapterResponse: {
            /** Audio File Path */
            audio_file_path: string | null;
            /**
             * Audio Generated Count
             * @default 0
             */
            audio_generated_count: number;
            /** Book Id */
            book_id: number;
            /** Chapter Number */
            chapter_number: number;
            /** Content File Name */
            content_file_name: string | null;
            /** Id */
            id: number;
            /**
             * Low Confidence Count
             * @default 0
             */
            low_confidence_count: number;
            /** Needs Reassembly */
            needs_reassembly: boolean;
            /** Preview Error */
            preview_error: string | null;
            /** Preview Status */
            preview_status: string | null;
            /**
             * Processed Sentence Count
             * @default 0
             */
            processed_sentence_count: number;
            /**
             * Sentence Count
             * @default 0
             */
            sentence_count: number;
            /** Smil File Path */
            smil_file_path: string | null;
            /** Summary */
            summary: string | null;
            /** Summary Updated At */
            summary_updated_at: string | null;
            /** Title */
            title: string | null;
        };
        /** CharacterResponse */
        CharacterResponse: {
            /** Aliases */
            aliases: string[] | null;
            /** Average Confidence */
            average_confidence: number | null;
            /** Book Id */
            book_id: number;
            /** Description */
            description: string | null;
            /** Evidence */
            evidence: string[] | null;
            /** Id */
            id: number;
            /** Is Narrator */
            is_narrator: boolean;
            /** Name */
            name: string;
            /**
             * Sentence Count
             * @default 0
             */
            sentence_count: number;
            /** Series Character Id */
            series_character_id: number | null;
            /** Shared Series Name */
            shared_series_name: string | null;
            /** Tts Seed */
            tts_seed: number | null;
            /** Tts Voice Id */
            tts_voice_id: string | null;
            /** Tts Voice Provider */
            tts_voice_provider: string | null;
            /** Voice Prompt */
            voice_prompt: string | null;
        };
        /** CharacterUpdate */
        CharacterUpdate: {
            /** Description */
            description?: string | null;
            /** Is Narrator */
            is_narrator?: boolean | null;
            /** Name */
            name?: string | null;
            /** Tts Seed */
            tts_seed?: number | null;
            /** Tts Voice Id */
            tts_voice_id?: string | null;
            /** Voice Prompt */
            voice_prompt?: string | null;
        };
        /** CharacterVoiceDesign */
        CharacterVoiceDesign: {
            /** Voice Prompt */
            voice_prompt?: string | null;
        };
        /** CleaningConfig */
        CleaningConfig: {
            /** Chapter Selectors */
            chapter_selectors: string[] | null;
            /** Content Selectors */
            content_selectors: string[] | null;
            /** Id */
            id: number;
            /** Name */
            name: string;
            /** Url Pattern */
            url_pattern: string;
        };
        /** CleaningConfigCreate */
        CleaningConfigCreate: {
            /** Chapter Selectors */
            chapter_selectors?: string[] | null;
            /** Content Selectors */
            content_selectors?: string[] | null;
            /** Name */
            name: string;
            /** Url Pattern */
            url_pattern: string;
        };
        /** CleaningConfigUpdate */
        CleaningConfigUpdate: {
            /** Chapter Selectors */
            chapter_selectors?: string[] | null;
            /** Content Selectors */
            content_selectors?: string[] | null;
            /** Name */
            name?: string | null;
            /** Url Pattern */
            url_pattern?: string | null;
        };
        /** ClientLogEntry */
        ClientLogEntry: {
            /**
             * Level
             * @default ERROR
             */
            level: string;
            /** Message */
            message: string;
            /** Source */
            source?: string | null;
        };
        /** CoverUrlRequest */
        CoverUrlRequest: {
            /** Url */
            url: string;
        };
        /** DatabaseHealth */
        DatabaseHealth: {
            /** Database */
            database: string;
            /** Status */
            status: string;
        };
        /** EndpointProbe */
        EndpointProbe: {
            /** Audio Bytes */
            audio_bytes?: number;
            /** Device */
            device?: string | null;
            /** Duration Ms */
            duration_ms: number;
            /** Endpoint */
            endpoint: string | null;
            /** Endpoint Id */
            endpoint_id: string | null;
            /** Error */
            error: string | null;
            /** Loaded Model */
            loaded_model?: string | null;
            /** Model */
            model: string | null;
            /** Priority */
            priority: number;
            /** Provider */
            provider: string | null;
            /** Response */
            response?: {
                [key: string]: unknown;
            };
            /** Service Status */
            service_status?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "ready" | "error";
        };
        /** EndpointResponse */
        EndpointResponse: {
            /**
             * Api Key Set
             * @default false
             */
            api_key_set: boolean;
            /** Base Url */
            base_url: string | null;
            /** Default Voice */
            default_voice: string | null;
            /** Id */
            id: string;
            /** Language */
            language: string | null;
            /** Model */
            model: string | null;
            /** Name */
            name: string;
            /** Provider */
            provider: string;
        };
        /** EndpointSpeedBuckets */
        EndpointSpeedBuckets: {
            /** From 5S To 15S */
            from_5s_to_15s: number;
            /** From 15S To 60S */
            from_15s_to_60s: number;
            /** Over 60S */
            over_60s: number;
            /** Under 5S */
            under_5s: number;
        };
        /** EndpointStats */
        EndpointStats: {
            /** Answered */
            answered: number;
            /** Answered 24H */
            answered_24h: number;
            /** Average 24H Ms */
            average_24h_ms: number | null;
            /** Average Ms */
            average_ms: number | null;
            /** Endpoint Id */
            endpoint_id: string;
            /** Failed */
            failed: number;
            /** Fastest Ms */
            fastest_ms: number | null;
            /** Last Answered At */
            last_answered_at: string | null;
            /** Model */
            model: string | null;
            /** Name */
            name: string;
            /** P50 Ms */
            p50_ms: number | null;
            /** P95 Ms */
            p95_ms: number | null;
            /** Provider */
            provider: string;
            /** Requests */
            requests: number;
            /** Slowest Ms */
            slowest_ms: number | null;
            speed_buckets: components["schemas"]["EndpointSpeedBuckets"];
            /** Success Rate */
            success_rate: number | null;
        };
        /** EndpointStatsResponse */
        EndpointStatsResponse: {
            /** Endpoints */
            endpoints: components["schemas"]["EndpointStats"][];
        };
        /** EndpointUpdate */
        EndpointUpdate: {
            /** Api Key */
            api_key?: string | null;
            /** Base Url */
            base_url?: string | null;
            /** Default Voice */
            default_voice?: string | null;
            /** Id */
            id: string;
            /** Language */
            language?: string | null;
            /** Model */
            model?: string | null;
            /** Name */
            name: string;
            /** Provider */
            provider: string;
        };
        /** EpubChapter */
        EpubChapter: {
            /** Content */
            content: string;
            /** Filename */
            filename: string;
            /** Title */
            title: string;
        };
        /** EpubPreview */
        EpubPreview: {
            /** Elements Removed */
            elements_removed: number;
            /** Estimated Word Count */
            estimated_word_count: number;
        };
        /** EpubUploadResult */
        EpubUploadResult: {
            book: components["schemas"]["Book"] | null;
            /** Error */
            error: string | null;
            /** Filename */
            filename: string;
            /** Status */
            status: string;
        };
        /** FileSize */
        FileSize: {
            /** Path */
            path: string;
            /** Size Bytes */
            size_bytes: number;
        };
        /** GenreFacet */
        GenreFacet: {
            /** Count */
            count: number;
            /** Name */
            name: string;
        };
        /** HealthReport */
        HealthReport: {
            database: components["schemas"]["StatusResponse"];
            /** Generated At */
            generated_at: string;
            liveness: components["schemas"]["StatusResponse"];
            /** Providers */
            providers: components["schemas"]["ProviderHealth"][];
            /** Status */
            status: string;
            storage: components["schemas"]["StorageHealth"];
            workers: components["schemas"]["WorkerHealth"];
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HumanAudiobookRebuildPreview */
        HumanAudiobookRebuildPreview: {
            /** Current Pipeline Version */
            current_pipeline_version: number;
            /** Realign Count */
            realign_count: number;
            /** Rebuild Count */
            rebuild_count: number;
            /** Total Count */
            total_count: number;
            /** Unavailable Count */
            unavailable_count: number;
            /** Up To Date Count */
            up_to_date_count: number;
        };
        /** ImportedAudiobookResponse */
        ImportedAudiobookResponse: {
            /** Alignment Error */
            alignment_error: string | null;
            /** Alignment Method */
            alignment_method: string | null;
            /** Asin */
            asin: string | null;
            /** Audio Size Bytes */
            audio_size_bytes: number;
            /** Book Id */
            book_id: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Derived Format Version */
            derived_format_version: number;
            /** Derived Revision */
            derived_revision: number;
            /** Duration Ms */
            duration_ms: number | null;
            /** Error */
            error: string | null;
            /** Id */
            id: number;
            /**
             * Is Reader Default
             * @default false
             */
            is_reader_default: boolean;
            /** Name */
            name: string;
            /** Needs Rebuild */
            needs_rebuild: boolean;
            /** Needs Upgrade */
            needs_upgrade: boolean;
            /** Original Filenames */
            original_filenames: string[];
            /** Pipeline Version */
            pipeline_version: number;
            /** Progress Current */
            progress_current: number;
            /** Progress Detail */
            progress_detail: string | null;
            /** Progress Total */
            progress_total: number;
            /** Source Manifest Sha256 */
            source_manifest_sha256: string | null;
            /** Source Size Bytes */
            source_size_bytes: number | null;
            /** Source Type */
            source_type: string;
            /** Status */
            status: string;
            /** Tracks */
            tracks: components["schemas"]["ImportedTrackResponse"][];
        };
        /** ImportedCueResponse */
        ImportedCueResponse: {
            /** Clip Begin Ms */
            clip_begin_ms: number;
            /** Clip End Ms */
            clip_end_ms: number;
            /** Confidence */
            confidence: number | null;
            /** Html Element Id */
            html_element_id: string;
            /** Method */
            method: string;
            /** Reading Block Index */
            reading_block_index: number | null;
            /** Reading Block Type */
            reading_block_type: string | null;
            /** Sentence Id */
            sentence_id: number;
            /** Text */
            text: string;
        };
        /** ImportedTrackMatchUpdate */
        ImportedTrackMatchUpdate: {
            /** Chapter Id */
            chapter_id?: number | null;
        };
        /** ImportedTrackResponse */
        ImportedTrackResponse: {
            /** Alignment Score */
            alignment_score: number | null;
            /** Audio Url */
            audio_url: string;
            /** Cue Count */
            cue_count: number;
            /** Cues Url */
            cues_url: string;
            /** Duration Ms */
            duration_ms: number;
            /** Id */
            id: number;
            /** Match Method */
            match_method: string | null;
            /** Matched Chapter Id */
            matched_chapter_id: number | null;
            /** Matched Chapter Title */
            matched_chapter_title: string | null;
            /** Media Type */
            media_type: string;
            /** Sequence Order */
            sequence_order: number;
            /** Smil Url */
            smil_url: string | null;
            /** Source End Ms */
            source_end_ms: number;
            /** Source Start Ms */
            source_start_ms: number;
            /** Title */
            title: string;
        };
        /** ImportPreviewItem */
        ImportPreviewItem: {
            /** Author */
            author: string | null;
            /** Cleaning Configs */
            cleaning_configs: string[];
            /** Detail */
            detail: string | null;
            /** Duplicate Book Id */
            duplicate_book_id: number | null;
            /** Input Type */
            input_type: string;
            /** Key */
            key: string;
            /** Name */
            name: string;
            /** Series */
            series: string | null;
            /** Source Url */
            source_url: string | null;
            /** Status */
            status: string;
            /** Title */
            title: string | null;
        };
        /** ImportPreviewResponse */
        ImportPreviewResponse: {
            /** Duplicate Count */
            duplicate_count: number;
            /** Error Count */
            error_count: number;
            /** Items */
            items: components["schemas"]["ImportPreviewItem"][];
            /** Ready Count */
            ready_count: number;
            /** Unsupported Count */
            unsupported_count: number;
        };
        /** JobMetrics */
        JobMetrics: {
            aggregate: components["schemas"]["JobMetricSummary"];
            /** By Job Type */
            by_job_type: {
                [key: string]: components["schemas"]["JobMetricSummary"];
            };
            /** Generated At */
            generated_at: string;
            /** Window Hours */
            window_hours: number;
        };
        /** JobMetricSummary */
        JobMetricSummary: {
            /** Average Duration Ms */
            average_duration_ms: number | null;
            /** Average Queue Delay Ms */
            average_queue_delay_ms: number | null;
            /** Canceled */
            canceled: number;
            /** Completed */
            completed: number;
            /** Failed */
            failed: number;
            /** Queued */
            queued: number;
            /** Retries */
            retries: number;
            /** Running */
            running: number;
            /** Total */
            total: number;
        };
        /** LibationBackupMatchResponse */
        LibationBackupMatchResponse: {
            /** Book Author */
            book_author: string | null;
            /** Book Id */
            book_id: number | null;
            /** Book Title */
            book_title: string | null;
            /** Candidates */
            candidates: components["schemas"]["LibationBookOptionResponse"][];
            /** Detail */
            detail: string | null;
            /** Existing Audiobooks */
            existing_audiobooks: components["schemas"]["LibationExistingAudioResponse"][];
            /** Existing Edition Id */
            existing_edition_id: number | null;
            /** File Count */
            file_count: number;
            /** Folder Name */
            folder_name: string;
            /** Match Method */
            match_method: string | null;
            /** Product Id */
            product_id: string;
            /** Source Key */
            source_key: string;
            /** Source Title */
            source_title: string;
            /** Status */
            status: string;
        };
        /** LibationBackupPreviewRequest */
        LibationBackupPreviewRequest: {
            /** Source Paths */
            source_paths: string[];
        };
        /** LibationBackupPreviewResponse */
        LibationBackupPreviewResponse: {
            /** Already Imported Count */
            already_imported_count: number;
            /** Ambiguous Count */
            ambiguous_count: number;
            /** Existing Audio Match Count */
            existing_audio_match_count: number;
            /** Groups */
            groups: components["schemas"]["LibationBackupMatchResponse"][];
            /** Ignored File Count */
            ignored_file_count: number;
            /** Library Books */
            library_books: components["schemas"]["LibationBookOptionResponse"][];
            /** Matched Count */
            matched_count: number;
            /** Unmatched Count */
            unmatched_count: number;
        };
        /** LibationBookOptionResponse */
        LibationBookOptionResponse: {
            /** Book Author */
            book_author: string | null;
            /** Book Id */
            book_id: number;
            /** Book Series */
            book_series: string | null;
            /** Book Title */
            book_title: string;
            /** Existing Audiobooks */
            existing_audiobooks: components["schemas"]["LibationExistingAudioResponse"][];
            /** Match Score */
            match_score: number | null;
        };
        /** LibationExistingAudioResponse */
        LibationExistingAudioResponse: {
            /** Edition Id */
            edition_id: number;
            /** Name */
            name: string;
            /** Product Id */
            product_id: string | null;
            /** Source Type */
            source_type: string;
            /** Status */
            status: string;
        };
        /** LibraryBookInfo */
        LibraryBookInfo: {
            /** Audio Playable */
            audio_playable: boolean;
            /** Has Epub */
            has_epub: boolean;
            /** Id */
            id: number;
            /** Universe Id */
            universe_id: number | null;
            /** Universe Name */
            universe_name: string | null;
        };
        /** LibraryFileIssue */
        LibraryFileIssue: {
            /** Author */
            author: string | null;
            /** Book Id */
            book_id: number;
            /** Issue */
            issue: string;
            /** Path */
            path?: string;
            /** Source Url */
            source_url?: string;
            /** Title */
            title: string | null;
        };
        /** LibraryGroup */
        LibraryGroup: {
            /** Audio Count */
            audio_count: number;
            /** Author */
            author: string | null;
            /** Author Count */
            author_count: number;
            /** Book Count */
            book_count: number;
            /** Cover Ids */
            cover_ids: number[];
            /** Name */
            name: string | null;
            /** Universe Id */
            universe_id: number | null;
        };
        /** LibraryGroupsPage */
        LibraryGroupsPage: {
            facets: components["schemas"]["CatalogFacets"];
            /** Items */
            items: components["schemas"]["LibraryGroup"][];
            /** Next Cursor */
            next_cursor: string | null;
            /** Total Count */
            total_count: number | null;
        };
        /** LibraryValidation */
        LibraryValidation: {
            /** Issues */
            issues: components["schemas"]["LibraryFileIssue"][];
            /** Issues Count */
            issues_count: number;
            /** Total Books */
            total_books: number;
        };
        /** LifecycleDefinition */
        LifecycleDefinition: {
            /** Active States */
            active_states: (string | null)[];
            /** Failure States */
            failure_states: (string | null)[];
            /** Groups */
            groups: {
                [key: string]: (string | null)[];
            };
            /** Name */
            name: string;
            /** Recovery */
            recovery: {
                [key: string]: string | null;
            };
            /** Retryable States */
            retryable_states: (string | null)[];
            /** States */
            states: components["schemas"]["LifecycleState"][];
            /** Terminal States */
            terminal_states: (string | null)[];
        };
        /** LifecycleState */
        LifecycleState: {
            /** Label */
            label: string;
            /** Value */
            value: string | null;
        };
        /** LLMTest */
        LLMTest: {
            /** Endpoint */
            endpoint?: string | null;
            /** Model */
            model: string | null;
            /** Provider */
            provider: string | null;
            /** Response */
            response: {
                [key: string]: unknown;
            } | string | null;
            /** Results */
            results?: components["schemas"]["EndpointProbe"][];
            /**
             * Status
             * @enum {string}
             */
            status: "ready" | "partial" | "failed";
        };
        /** LogEntry */
        LogEntry: {
            /** Exception */
            exception?: string;
            /** Job Id */
            job_id?: number;
            /** Level */
            level: string;
            /** Logger */
            logger: string;
            /** Message */
            message: string;
            /** Request Id */
            request_id?: string;
            /** Timestamp */
            timestamp: string;
        };
        /** MetadataJobRequest */
        MetadataJobRequest: {
            /** Book Ids */
            book_ids?: number[] | null;
            /**
             * Trigger
             * @default manual
             */
            trigger: string;
        };
        /** MetadataMatch */
        MetadataMatch: {
            /** Approved At */
            approved_at: string | null;
            /** Book Id */
            book_id: number;
            /** Id */
            id: number;
            /** Last Checked At */
            last_checked_at: string | null;
            /** Match Confidence */
            match_confidence: number | null;
            /** Match Issues */
            match_issues: string[] | null;
            /** Note */
            note: string | null;
            /** Possible Missing Series Books */
            possible_missing_series_books: string[] | null;
            /** Proposed Genre Tags */
            proposed_genre_tags: string[] | null;
            /** Rejected At */
            rejected_at: string | null;
            /** Remote Author */
            remote_author: string | null;
            /** Remote Ids */
            remote_ids: {
                [key: string]: unknown;
            } | null;
            /** Remote Metadata */
            remote_metadata: {
                [key: string]: unknown;
            } | null;
            /** Remote Title */
            remote_title: string | null;
            /** Remote Url */
            remote_url: string | null;
            /** Source */
            source: string | null;
            /** Status */
            status: string;
        };
        /** MetadataProposalSummary */
        MetadataProposalSummary: {
            /** Book Author */
            book_author: string;
            /** Book Id */
            book_id: number;
            /** Book Series */
            book_series: string | null;
            /** Book Series Index */
            book_series_index: number | null;
            /** Book Title */
            book_title: string;
            /** Candidate Matches */
            candidate_matches: components["schemas"]["MetadataMatch"][];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Id */
            id: number;
            match: components["schemas"]["MetadataMatch"] | null;
            /** Note */
            note: string | null;
            /** Possible Missing Series Books */
            possible_missing_series_books: string[];
            /** Proposed Genre Tags */
            proposed_genre_tags: string[];
            /** Reviewed At */
            reviewed_at: string | null;
            /** Status */
            status: string;
        };
        /** MetadataSyncApplyRequest */
        MetadataSyncApplyRequest: {
            /** Book Ids */
            book_ids?: number[] | null;
        };
        /** MetadataSyncApplyResponse */
        MetadataSyncApplyResponse: {
            /** Books With Missing Series Candidates */
            books_with_missing_series_candidates: number;
            /** Books With New Genres */
            books_with_new_genres: number;
            /** Matched Books */
            matched_books: number;
            /** Results */
            results: components["schemas"]["MetadataSyncBookResult"][];
            /** Scanned Books */
            scanned_books: number;
            /** Updated Books */
            updated_books: number;
        };
        /** MetadataSyncBookResult */
        MetadataSyncBookResult: {
            /** Author */
            author: string;
            /** Book Id */
            book_id: number;
            /** Genre Tags */
            genre_tags: string[];
            /**
             * Match Confidence
             * @default 0
             */
            match_confidence: number;
            /** Match Issues */
            match_issues: string[];
            /** Matched */
            matched: boolean;
            /** Metadata Details */
            metadata_details: {
                [key: string]: unknown;
            } | null;
            /** New Genre Tags */
            new_genre_tags: string[];
            /** Note */
            note: string | null;
            /** Possible Missing Series Books */
            possible_missing_series_books: string[];
            /** Remote Author */
            remote_author: string | null;
            /** Remote Ids */
            remote_ids: {
                [key: string]: unknown;
            } | null;
            /** Remote Title */
            remote_title: string | null;
            /** Remote Url */
            remote_url: string | null;
            /** Source */
            source: string | null;
            /** Title */
            title: string;
        };
        /** MetadataSyncJob */
        MetadataSyncJob: {
            /** Applied Books */
            applied_books: number;
            /** Completed At */
            completed_at: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Error */
            error: string | null;
            /** Id */
            id: number;
            /** Matched Books */
            matched_books: number;
            /** Processed Books */
            processed_books: number;
            /** Proposed Books */
            proposed_books: number;
            /** Started At */
            started_at: string | null;
            /** Status */
            status: string;
            /** Total Books */
            total_books: number;
            /** Trigger */
            trigger: string;
        };
        /** MetadataSyncPreviewRequest */
        MetadataSyncPreviewRequest: {
            /** Book Ids */
            book_ids?: number[] | null;
        };
        /** MetadataSyncPreviewResponse */
        MetadataSyncPreviewResponse: {
            /** Books With Missing Series Candidates */
            books_with_missing_series_candidates: number;
            /** Books With New Genres */
            books_with_new_genres: number;
            /** Matched Books */
            matched_books: number;
            /** Results */
            results: components["schemas"]["MetadataSyncBookResult"][];
            /** Scanned Books */
            scanned_books: number;
        };
        /** OkResponse */
        OkResponse: {
            /** Ok */
            ok: boolean;
        };
        /** PipelinePaused */
        PipelinePaused: {
            /** Pause Requested */
            pause_requested: boolean;
            /** Status */
            status: string | null;
        };
        /** PipelineQueued */
        PipelineQueued: {
            /** Batch Limit */
            batch_limit?: number;
            /** Queued */
            queued: boolean;
            /** Status */
            status: string | null;
            /** Stop After Phase */
            stop_after_phase?: string;
        };
        /** PreviewCleaningRequest */
        PreviewCleaningRequest: {
            /**
             * Content Selectors
             * @default []
             */
            content_selectors: string[];
            /**
             * Removed Chapters
             * @default []
             */
            removed_chapters: string[];
        };
        /** ProcessingJob */
        ProcessingJob: {
            /** Attempt Count */
            attempt_count: number;
            /**
             * Available At
             * Format: date-time
             */
            available_at: string;
            /** Book Id */
            book_id: number | null;
            /** Book Title */
            book_title: string | null;
            /** Cancel Requested */
            cancel_requested: boolean;
            /** Completed At */
            completed_at: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Error */
            error: string | null;
            /** Heartbeat At */
            heartbeat_at: string | null;
            /** Id */
            id: number;
            /** Job Type */
            job_type: string;
            /** Lease Expires At */
            lease_expires_at: string | null;
            /** Max Attempts */
            max_attempts: number;
            /** Parent Job Id */
            parent_job_id: number | null;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Progress Current */
            progress_current: number;
            /** Progress Detail */
            progress_detail: string | null;
            /** Progress Total */
            progress_total: number;
            /** Request Id */
            request_id: string;
            /** Resource Lane */
            resource_lane: string;
            /** Started At */
            started_at: string | null;
            /** Status */
            status: string;
            /** Target Content Version */
            target_content_version: number | null;
            /** Target Id */
            target_id: number | null;
            /** Target Type */
            target_type: string | null;
        };
        /** ProcessingJobRequest */
        ProcessingJobRequest: {
            /** Book Ids */
            book_ids?: number[];
            /**
             * Job Type
             * @enum {string}
             */
            job_type: "clean_book" | "clean_all" | "refresh_book" | "refresh_all" | "audiobook_pipeline" | "import_audiobook" | "upgrade_imported_audiobook" | "rebuild_imported_audiobook" | "rematch_imported_audiobook" | "align_imported_audiobook" | "metadata_sync" | "generate_sentence_audio" | "generate_chapter_preview" | "retry_cover" | "create_backup" | "verify_backup";
            /** Payload */
            payload?: {
                [key: string]: unknown;
            };
            /** Target Id */
            target_id?: number | null;
        };
        /** ProcessingJobsCreated */
        ProcessingJobsCreated: {
            /** Jobs */
            jobs: components["schemas"]["ProcessingJob"][];
        };
        /** ProviderHealth */
        ProviderHealth: {
            /** Capability */
            capability: string;
            /** Configured Endpoints */
            configured_endpoints: number;
            /** Status */
            status: string;
        };
        /** PurgedBooks */
        PurgedBooks: {
            /** Purged */
            purged: number;
        };
        /** QueuedImports */
        QueuedImports: {
            /** Queued Count */
            queued_count: number;
            /** Skipped Count */
            skipped_count: number;
        };
        /** ReaderAudiobookCapability */
        ReaderAudiobookCapability: {
            /** Manifest Url */
            manifest_url: string;
            /** Ready Audio Bytes */
            ready_audio_bytes: number;
            /** Ready Chapter Count */
            ready_chapter_count: number;
            /** Revision */
            revision: number;
            /** Source Content Version */
            source_content_version: number;
            /**
             * Status
             * @enum {string}
             */
            status: "stale" | "processing" | "partial" | "complete" | "error";
            /** Text Content Version */
            text_content_version: number;
            /** Total Chapter Count */
            total_chapter_count: number;
        };
        /** ReaderAudiobookChapter */
        ReaderAudiobookChapter: {
            /** Audio Sha256 */
            audio_sha256: string | null;
            /** Audio Size Bytes */
            audio_size_bytes: number | null;
            /** Audio Url */
            audio_url: string | null;
            /** Audio Version */
            audio_version: number | null;
            /** Duration Ms */
            duration_ms: number | null;
            /** Href */
            href: string;
            /** Key */
            key: string;
            /** Smil Sha256 */
            smil_sha256: string | null;
            /** Smil Size Bytes */
            smil_size_bytes: number | null;
            /** Smil Url */
            smil_url: string | null;
            /**
             * State
             * @enum {string}
             */
            state: "pending" | "processing" | "ready" | "error";
            /** Title */
            title: string | null;
        };
        /** ReaderAudiobookManifest */
        ReaderAudiobookManifest: {
            /** Chapters */
            chapters: components["schemas"]["ReaderAudiobookChapter"][];
            /** Revision */
            revision: number;
            /** Source Content Version */
            source_content_version: number;
            text: components["schemas"]["ReaderAudiobookTextAsset"];
        };
        /** ReaderAudiobookTextAsset */
        ReaderAudiobookTextAsset: {
            /** Content Version */
            content_version: number;
            /** Sha256 */
            sha256: string;
            /** Size Bytes */
            size_bytes: number;
            /** Url */
            url: string;
        };
        /** ReaderBook */
        ReaderBook: {
            audiobook: components["schemas"]["ReaderAudiobookCapability"] | null;
            /** Audiobook Types */
            audiobook_types: ("ai_generated" | "human_narrated")[];
            /** Author */
            author: string;
            /**
             * Content Updated At
             * Format: date-time
             */
            content_updated_at: string;
            /** Content Version */
            content_version: number;
            /** Cover Url */
            cover_url: string | null;
            /** Current Word Count */
            current_word_count: number | null;
            /** Download Url */
            download_url: string | null;
            /** Effective Genre Tags */
            effective_genre_tags: string[];
            /**
             * Has Text
             * @default true
             */
            has_text: boolean;
            /** Id */
            id: number;
            /** Series */
            series: string | null;
            /** Series Index */
            series_index: number | null;
            source_type: components["schemas"]["SourceType"];
            /** Source Url */
            source_url: string | null;
            /** Title */
            title: string;
        };
        /** ReaderSeriesSummary */
        ReaderSeriesSummary: {
            /** Book Count */
            book_count: number;
            /** Cover Url */
            cover_url: string | null;
            /** Genre Tags */
            genre_tags: string[];
            /** Latest Update */
            latest_update: string | null;
            /** Name */
            name: string;
            /** Total Words */
            total_words: number;
        };
        /** RebuiltImports */
        RebuiltImports: {
            /** Pipeline Version */
            pipeline_version: number;
            /** Queued Count */
            queued_count: number;
            /** Skipped Count */
            skipped_count: number;
        };
        /** RecycleBin */
        RecycleBin: {
            /** Books */
            books: components["schemas"]["RecycledBook"][];
            /** Retention Days */
            retention_days: number;
        };
        /** RecycledBook */
        RecycledBook: {
            /**
             * Audiobook Enabled
             * @default false
             */
            audiobook_enabled: boolean;
            /** Audiobook Pipeline Status */
            audiobook_pipeline_status: string | null;
            /** Audiobook Tts Provider */
            audiobook_tts_provider: string | null;
            /** Author */
            author: string;
            /** Content Selectors */
            content_selectors: string[] | null;
            /**
             * Content Updated At
             * Format: date-time
             */
            content_updated_at: string;
            /** Content Version */
            content_version: number;
            /** Cover Path */
            cover_path: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Current Path */
            current_path: string | null;
            /** Current Word Count */
            current_word_count: number | null;
            /** Deleted At */
            deleted_at: string | null;
            /** Download Status */
            download_status: string | null;
            /** Genre Tags */
            genre_tags: string[] | null;
            /** Id */
            id: number;
            /** Immutable Path */
            immutable_path: string | null;
            /** Master Word Count */
            master_word_count: number | null;
            /** Metadata Details */
            metadata_details: {
                [key: string]: unknown;
            } | null;
            /** Metadata Remote Ids */
            metadata_remote_ids: {
                [key: string]: unknown;
            } | null;
            /** Metadata Sync Source */
            metadata_sync_source: string | null;
            /** Metadata Synced At */
            metadata_synced_at: string | null;
            /** Notes */
            notes: string | null;
            /** Purge After */
            purge_after: string | null;
            /** Recovery Files Available */
            recovery_files_available: boolean;
            /** Refresh Status */
            refresh_status: string | null;
            /** Removed Chapters */
            removed_chapters: string[] | null;
            /** Series */
            series: string | null;
            /** Series Index */
            series_index: number | null;
            /** Source Tags */
            source_tags: string[] | null;
            source_type: components["schemas"]["SourceType"];
            /** Source Url */
            source_url: string | null;
            /** Title */
            title: string;
            /** Updated At */
            updated_at: string | null;
            /** User Genre Tags */
            user_genre_tags: string[] | null;
        };
        /** RemoveAllBooks */
        RemoveAllBooks: {
            /** Book Count */
            book_count: number;
            /** Books */
            books: components["schemas"]["BookRemovalPreview"][];
            /** Dry Run */
            dry_run: boolean;
            /** File Count */
            file_count: number;
            /** Log Count */
            log_count: number;
            /** Paths */
            paths: string[];
            /** Recoverable */
            recoverable: boolean;
            /** Retention Days */
            retention_days: number;
            /** Total Bytes */
            total_bytes: number;
        };
        /** ReprocessStatus */
        ReprocessStatus: {
            /** Error */
            error?: string;
            /** Job Id */
            job_id?: number;
            /** Processed */
            processed?: number;
            /** Running */
            running: boolean;
            /** Status */
            status?: string;
            /** Total */
            total?: number;
        };
        /** RosterShared */
        RosterShared: {
            /** Books Updated */
            books_updated: number;
            /** Profiles */
            profiles: number;
            /** Series */
            series: string;
        };
        /** SchedulerConfigUpdate */
        SchedulerConfigUpdate: {
            /** Time Local */
            time_local: string;
            /** Timezone */
            timezone: string;
        };
        /** SchedulerJobStatus */
        SchedulerJobStatus: {
            /** Job Id */
            job_id: string;
            /** Last Run Completed At */
            last_run_completed_at: string | null;
            /** Last Run Started At */
            last_run_started_at: string | null;
            /** Last Run Status */
            last_run_status: string | null;
            /** Next Run At */
            next_run_at: string | null;
            /** Run In Progress */
            run_in_progress: boolean;
            /** Schedule */
            schedule: string;
            /**
             * Schedule Mode
             * @default interval
             */
            schedule_mode: string;
            /** Schedule Time Local */
            schedule_time_local: string | null;
            /** Schedule Timezone */
            schedule_timezone: string | null;
            /** Scheduler Running */
            scheduler_running: boolean;
        };
        /** SchedulerTriggered */
        SchedulerTriggered: {
            /** Message */
            message: string;
            /** Processing Job Id */
            processing_job_id: number;
        };
        /** SentenceListResponse */
        SentenceListResponse: {
            /** Items */
            items: components["schemas"]["SentenceResponse"][];
            /** Limit */
            limit: number;
            /** Page */
            page: number;
            /** Total */
            total: number;
        };
        /** SentenceQueued */
        SentenceQueued: {
            /** Batch Limit */
            batch_limit?: number;
            /** Queued */
            queued: boolean;
            /** Sentence Id */
            sentence_id: number;
            /** Status */
            status: string | null;
            /** Stop After Phase */
            stop_after_phase?: string;
        };
        /** SentenceResponse */
        SentenceResponse: {
            /** Audio Duration Ms */
            audio_duration_ms: number | null;
            /** Audio File Path */
            audio_file_path: string | null;
            /** Chapter Id */
            chapter_id: number;
            /** Character Id */
            character_id: number | null;
            /** Generation Group Id */
            generation_group_id: string | null;
            /** Html Element Id */
            html_element_id: string;
            /** Id */
            id: number;
            /** Original Text */
            original_text: string;
            /** Reading Block Index */
            reading_block_index: number | null;
            /** Reading Block Type */
            reading_block_type: string | null;
            /** Sequence Order */
            sequence_order: number;
            /** Speaker Confidence */
            speaker_confidence: number | null;
            /** Speaker Reason */
            speaker_reason: string | null;
            /** Status */
            status: string;
            /** Tagged Text */
            tagged_text: string | null;
            /** Tts Attempts */
            tts_attempts: number | null;
            /** Voice Similarity */
            voice_similarity: number | null;
        };
        /** SentenceUpdate */
        SentenceUpdate: {
            /** Character Id */
            character_id?: number | null;
            /** Tagged Text */
            tagged_text?: string | null;
        };
        /** SeriesDetected */
        SeriesDetected: {
            /** Series Detected */
            series_detected: string[];
            /** Updated */
            updated: number;
        };
        /** SeriesGenresUpdate */
        SeriesGenresUpdate: {
            /** User Genre Tags */
            user_genre_tags?: string[];
        };
        /** SeriesMerge */
        SeriesMerge: {
            /** Source */
            source: string;
            /** Target */
            target: string;
        };
        /** SeriesMerged */
        SeriesMerged: {
            /** Merged */
            merged: number;
            /** Source */
            source: string;
            /** Target */
            target: string;
        };
        /** SeriesMetadataSummary */
        SeriesMetadataSummary: {
            /** Series Name */
            series_name: string;
            /** User Genre Tags */
            user_genre_tags: string[];
        };
        /** SeriesRename */
        SeriesRename: {
            /** New Name */
            new_name: string;
        };
        /** SeriesRenamed */
        SeriesRenamed: {
            /** New Name */
            new_name: string;
            /** Old Name */
            old_name: string;
            /** Updated */
            updated: number;
        };
        /** SeriesReorder */
        SeriesReorder: {
            /** Ordered Book Ids */
            ordered_book_ids: number[];
        };
        /** SeriesReordered */
        SeriesReordered: {
            /** Series */
            series: string;
            /** Updated */
            updated: number;
        };
        /** SettingsResponse */
        SettingsResponse: {
            /** Diarization Prompt Template */
            diarization_prompt_template: string | null;
            /** Id */
            id: number | null;
            /** Llm Api Key Set */
            llm_api_key_set: boolean;
            /** Llm Base Url */
            llm_base_url: string | null;
            /** Llm Endpoints */
            llm_endpoints: components["schemas"]["EndpointResponse"][];
            /** Llm Model */
            llm_model: string | null;
            /** Llm Provider */
            llm_provider: string | null;
            /** Roster Prompt Template */
            roster_prompt_template: string | null;
            /** Transcription Api Key Set */
            transcription_api_key_set: boolean;
            /** Transcription Base Url */
            transcription_base_url: string | null;
            /** Transcription Endpoints */
            transcription_endpoints: components["schemas"]["EndpointResponse"][];
            /** Transcription Language */
            transcription_language: string | null;
            /** Transcription Model */
            transcription_model: string | null;
            /** Transcription Provider */
            transcription_provider: string;
            /** Tts Api Key Set */
            tts_api_key_set: boolean;
            /** Tts Base Url */
            tts_base_url: string | null;
            /** Tts Default Voice */
            tts_default_voice: string | null;
            /** Tts Endpoints */
            tts_endpoints: components["schemas"]["EndpointResponse"][];
            /** Tts Max Block Chars */
            tts_max_block_chars: number;
            /** Tts Model */
            tts_model: string | null;
            /** Tts Provider */
            tts_provider: string | null;
            /** Tts Quality Attempts */
            tts_quality_attempts: number;
            /** Tts Voice Similarity Threshold */
            tts_voice_similarity_threshold: number;
        };
        /** SettingsUpdate */
        SettingsUpdate: {
            /** Diarization Prompt Template */
            diarization_prompt_template?: string | null;
            /** Llm Api Key */
            llm_api_key?: string | null;
            /** Llm Base Url */
            llm_base_url?: string | null;
            /** Llm Endpoints */
            llm_endpoints?: components["schemas"]["EndpointUpdate"][] | null;
            /** Llm Model */
            llm_model?: string | null;
            /** Llm Provider */
            llm_provider?: string | null;
            /** Roster Prompt Template */
            roster_prompt_template?: string | null;
            /** Transcription Api Key */
            transcription_api_key?: string | null;
            /** Transcription Base Url */
            transcription_base_url?: string | null;
            /** Transcription Endpoints */
            transcription_endpoints?: components["schemas"]["EndpointUpdate"][] | null;
            /** Transcription Language */
            transcription_language?: string | null;
            /** Transcription Model */
            transcription_model?: string | null;
            /** Transcription Provider */
            transcription_provider?: string | null;
            /** Tts Api Key */
            tts_api_key?: string | null;
            /** Tts Base Url */
            tts_base_url?: string | null;
            /** Tts Default Voice */
            tts_default_voice?: string | null;
            /** Tts Endpoints */
            tts_endpoints?: components["schemas"]["EndpointUpdate"][] | null;
            /** Tts Max Block Chars */
            tts_max_block_chars?: number | null;
            /** Tts Model */
            tts_model?: string | null;
            /** Tts Provider */
            tts_provider?: string | null;
            /** Tts Quality Attempts */
            tts_quality_attempts?: number | null;
            /** Tts Voice Similarity Threshold */
            tts_voice_similarity_threshold?: number | null;
        };
        /**
         * SourceType
         * @enum {string}
         */
        SourceType: "web" | "epub" | "audiobook";
        /** StatusResponse */
        StatusResponse: {
            /** Status */
            status: string;
        };
        /** StorageCleanup */
        StorageCleanup: {
            /** Books */
            books: components["schemas"]["LibraryFileIssue"][];
            /** Dry Run */
            dry_run: boolean;
            /** Files */
            files: components["schemas"]["FileSize"][];
            /** Skipped Reason */
            skipped_reason?: string;
            /** Total Bytes */
            total_bytes: number;
        };
        /** StorageHealth */
        StorageHealth: {
            /** Free Bytes */
            free_bytes?: number;
            /** Minimum Free Bytes */
            minimum_free_bytes?: number;
            /** Percent Free */
            percent_free?: number;
            /** Status */
            status: string;
            /** Total Bytes */
            total_bytes?: number;
            /** Writable */
            writable: boolean;
        };
        /** TranscriptionTest */
        TranscriptionTest: {
            /** Device */
            device: string | null;
            /** Endpoint */
            endpoint?: string | null;
            /** Model */
            model: string | null;
            /** Provider */
            provider: string | null;
            /** Results */
            results?: components["schemas"]["EndpointProbe"][];
            /**
             * Status
             * @enum {string}
             */
            status: "ready" | "partial" | "failed";
        };
        /** TTSProviderChanged */
        TTSProviderChanged: {
            /** Affected Book Ids */
            affected_book_ids: number[];
            /** Provider */
            provider: string;
            /**
             * Scope
             * @enum {string}
             */
            scope: "series" | "book";
        };
        /** TTSTest */
        TTSTest: {
            /** Audio Bytes */
            audio_bytes: number;
            /** Endpoint */
            endpoint?: string | null;
            /** Model */
            model: string | null;
            /** Provider */
            provider: string | null;
            /** Results */
            results?: components["schemas"]["EndpointProbe"][];
            /**
             * Status
             * @enum {string}
             */
            status: "ready" | "partial" | "failed";
        };
        /** UniverseMembership */
        UniverseMembership: {
            /** Book Id */
            book_id?: number | null;
            /** Name */
            name?: string | null;
            /** Series */
            series?: string | null;
        };
        /** UniverseMembershipResult */
        UniverseMembershipResult: {
            /** Universe Id */
            universe_id: number | null;
            /** Universe Name */
            universe_name: string | null;
        };
        /** UniverseSummary */
        UniverseSummary: {
            /** Id */
            id: number;
            /** Name */
            name: string;
        };
        /** UpdateTask */
        UpdateTask: {
            /** Completed At */
            completed_at: string | null;
            /** Completed Books */
            completed_books: number;
            /** Id */
            id: number;
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
            /** Status */
            status: string;
            /** Total Books */
            total_books: number;
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /** WebCheck */
        WebCheck: {
            /** Book Id */
            book_id: number;
            /** Entry Type */
            entry_type: string;
            /** New Chapter Count */
            new_chapter_count: number | null;
            /** Previous Chapter Count */
            previous_chapter_count: number | null;
            /** Timestamp */
            timestamp: string | null;
            /** Words Added */
            words_added: number | null;
        };
        /** WebNovelRequest */
        WebNovelRequest: {
            /**
             * Url
             * Format: uri
             */
            url: string;
        };
        /** WorkerHealth */
        WorkerHealth: {
            /** Active Workers */
            active_workers: number;
            /** Configured Workers */
            configured_workers: number;
            /** Failed Workers */
            failed_workers: number;
            /** Lanes */
            lanes: {
                [key: string]: number;
            };
            /** Running */
            running: boolean;
            /** Status */
            status: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    update_character_api_audiobook_characters__char_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                char_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CharacterUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CharacterResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    design_character_voice_api_audiobook_characters__char_id__design_voice_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                char_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CharacterVoiceDesign"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CharacterResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_character_voice_sample_api_audiobook_characters__char_id__voice_sample_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                char_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "audio/*": Blob;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rebuild_all_human_audiobooks_api_audiobook_imports_rebuild_all_post: {
        parameters: {
            query?: {
                force?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RebuiltImports"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_human_audiobook_rebuilds_api_audiobook_imports_rebuild_preview_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HumanAudiobookRebuildPreview"];
                };
            };
        };
    };
    upgrade_all_imported_audiobooks_api_audiobook_imports_upgrade_all_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueuedImports"];
                };
            };
        };
    };
    preview_libation_backup_api_audiobook_libation_backup_preview_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LibationBackupPreviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LibationBackupPreviewResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_sentence_api_audiobook_sentences__sentence_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                sentence_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SentenceUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SentenceResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_sentence_audio_api_audiobook_sentences__sentence_id__audio_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                sentence_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "audio/mpeg": Blob;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_settings_api_audiobook_settings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsResponse"];
                };
            };
        };
    };
    update_settings_api_audiobook_settings_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SettingsUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_endpoint_stats_api_audiobook_settings_endpoint_stats_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AllEndpointStatsResponse"];
                };
            };
        };
    };
    get_llm_endpoint_stats_api_audiobook_settings_llm_stats_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EndpointStatsResponse"];
                };
            };
        };
    };
    test_llm_settings_api_audiobook_settings_test_llm_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LLMTest"];
                };
            };
        };
    };
    test_transcription_settings_api_audiobook_settings_test_transcription_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TranscriptionTest"];
                };
            };
        };
    };
    test_tts_settings_api_audiobook_settings_test_tts_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TTSTest"];
                };
            };
        };
    };
    upload_audio_only_book_api_audiobooks_upload_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_audio_only_book_api_audiobooks_upload_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportedAudiobookResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    login_api_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AdminLoginRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminAuthStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    logout_api_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminAuthStatus"];
                };
            };
        };
    };
    auth_status_api_auth_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminAuthStatus"];
                };
            };
        };
    };
    get_backups_api_backups_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BackupInventory"];
                };
            };
        };
    };
    create_backup_api_backups_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessingJob"];
                };
            };
        };
    };
    delete_backup_api_backups__filename__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                filename: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_backup_api_backups__filename__download_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                filename: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/zip": Blob;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    verify_backup_api_backups__filename__verify_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                filename: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessingJob"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_all_books_api_books_get: {
        parameters: {
            query?: {
                limit?: number;
                skip?: number;
                sort_by?: string;
                sort_order?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_book_api_books__book_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_book_details_api_books__book_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BookUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_book_by_id_api_books__book_id__delete: {
        parameters: {
            query?: {
                permanent?: boolean;
            };
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rebuild_audio_only_api_books__book_id__audiobook_audio_rebuild_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PipelineQueued"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_chapters_api_books__book_id__audiobook_chapters_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChapterResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_chapter_audio_api_books__book_id__audiobook_chapters__chapter_id__audio_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
                chapter_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "audio/mpeg": Blob;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    generate_chapter_preview_api_books__book_id__audiobook_chapters__chapter_id__preview_audio_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
                chapter_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChapterPreviewQueued"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_characters_api_books__book_id__audiobook_characters_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CharacterResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_audiobook_api_books__book_id__audiobook_download_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/epub+zip": Blob;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_imported_audiobooks_api_books__book_id__audiobook_imports_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportedAudiobookResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_imported_audiobook_api_books__book_id__audiobook_imports_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_imported_audiobook_api_books__book_id__audiobook_imports_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportedAudiobookResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    pause_pipeline_api_books__book_id__audiobook_pause_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PipelinePaused"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rebuild_pipeline_api_books__book_id__audiobook_rebuild_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PipelineQueued"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rebuild_character_roster_api_books__book_id__audiobook_roster_rebuild_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PipelineQueued"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    share_character_roster_with_series_api_books__book_id__audiobook_roster_share_series_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RosterShared"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    run_pipeline_batch_api_books__book_id__audiobook_run_batch_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PipelineQueued"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_sentences_api_books__book_id__audiobook_sentences_get: {
        parameters: {
            query?: {
                chapter_id?: number | null;
                limit?: number;
                page?: number;
                review_only?: boolean;
            };
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SentenceListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    generate_sentence_audio_api_books__book_id__audiobook_sentences__sentence_id__generate_audio_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
                sentence_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SentenceQueued"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    start_pipeline_api_books__book_id__audiobook_start_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PipelineQueued"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_pipeline_status_api_books__book_id__audiobook_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AudiobookStatusResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    step_pipeline_api_books__book_id__audiobook_step_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PipelineQueued"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_book_tts_provider_api_books__book_id__audiobook_tts_provider_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BookTTSProviderUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TTSProviderChanged"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_book_chapters_api_books__book_id__chapters_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EpubChapter"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_book_cleaned_chapters_api_books__book_id__cleaned_chapters_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EpubChapter"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_book_cover_api_books__book_id__cover_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_book_cover_api_books__book_id__cover_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_cover_from_url_api_books__book_id__cover_url_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CoverUrlRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    detach_book_source_api_books__book_id__detach_source_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_book_api_books__book_id__download_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/epub+zip": Blob;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_book_matched_config_api_books__book_id__matched_config_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CleaningConfig"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_cleaning_api_books__book_id__preview_cleaning_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PreviewCleaningRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EpubPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    process_book_endpoint_api_books__book_id__process_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    refresh_book_api_books__book_id__refresh_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_original_epub_api_books__book_id__restore_original_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    retry_cover_api_books__book_id__retry_cover_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_book_revisions_api_books__book_id__revisions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BookRevision"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_book_revision_api_books__book_id__revisions__revision_id__restore_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
                revision_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_book_update_history_api_books__book_id__update_history_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BookChapterUpdateHistory"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_web_novel_api_books_add_web_novel_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WebNovelRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_book_by_title_api_books_by_title__title__delete: {
        parameters: {
            query?: {
                permanent?: boolean;
            };
            header?: never;
            path: {
                title: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_book_catalog_api_books_catalog_get: {
        parameters: {
            query?: {
                audiobook?: ("available" | "none" | "playable" | "unplayable") | null;
                cursor?: string | null;
                genre?: string | null;
                limit?: number;
                q?: string | null;
                review?: ("missing-series" | "refreshing" | "refresh-error") | null;
                series?: string | null;
                sort_by?: "title" | "author" | "word_count" | "updated_at" | "audiobook_enabled" | "series_index";
                sort_order?: "asc" | "desc";
                source?: ("web" | "epub" | "audiobook") | null;
                universe?: number | null;
                view?: "all" | "series" | "standalone" | "web";
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BookCatalogPage"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    count_books_endpoint_api_books_count_get: {
        parameters: {
            query?: {
                q?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BookCount"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_book_details_api_books_details_get: {
        parameters: {
            query: {
                ids: number[];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    detect_series_in_library_api_books_detect_series_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeriesDetected"];
                };
            };
        };
    };
    remove_all_books_api_books_remove_all_post: {
        parameters: {
            query?: {
                dry_run?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RemoveAllBooks"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reprocess_all_books_api_books_reprocess_all_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StatusResponse"];
                };
            };
        };
    };
    reprocess_all_status_api_books_reprocess_all_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReprocessStatus"];
                };
            };
        };
    };
    search_books_unified_api_books_search_get: {
        parameters: {
            query: {
                limit?: number;
                q: string;
                skip?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    search_books_by_author_api_books_search_author__author__get: {
        parameters: {
            query?: {
                limit?: number;
                skip?: number;
            };
            header?: never;
            path: {
                author: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    search_books_by_series_api_books_search_series__series__get: {
        parameters: {
            query?: {
                limit?: number;
                skip?: number;
            };
            header?: never;
            path: {
                series: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_epub_api_books_upload_epub_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_epub_api_books_upload_epub_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_epubs_api_books_upload_epubs_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_epubs_api_books_upload_epubs_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EpubUploadResult"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_cleaning_configs_api_cleaning_configs_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CleaningConfig"][];
                };
            };
        };
    };
    create_cleaning_config_endpoint_api_cleaning_configs_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CleaningConfigCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CleaningConfig"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_cleaning_config_endpoint_api_cleaning_configs__config_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                config_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CleaningConfig"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_cleaning_config_endpoint_api_cleaning_configs__config_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                config_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CleaningConfigUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CleaningConfig"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_cleaning_config_endpoint_api_cleaning_configs__config_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                config_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_cover_image_api_covers__book_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "image/*": Blob;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_attention_dashboard_api_dashboard_attention_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AttentionDashboard"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_imported_audiobook_api_imported_audiobooks__edition_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                edition_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    align_imported_audiobook_api_imported_audiobooks__edition_id__align_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                edition_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportedAudiobookResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rematch_imported_audiobook_api_imported_audiobooks__edition_id__rematch_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                edition_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportedAudiobookResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    retry_imported_audiobook_api_imported_audiobooks__edition_id__retry_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                edition_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportedAudiobookResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_imported_track_audio_api_imported_audiobooks__edition_id__tracks__track_id__audio_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                edition_id: number;
                track_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "audio/*": Blob;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_imported_track_cues_api_imported_audiobooks__edition_id__tracks__track_id__cues_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                edition_id: number;
                track_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportedCueResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    match_imported_track_api_imported_audiobooks__edition_id__tracks__track_id__match_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                edition_id: number;
                track_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ImportedTrackMatchUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportedTrackResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_imported_track_smil_api_imported_audiobooks__edition_id__tracks__track_id__smil_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                edition_id: number;
                track_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/smil+xml": string;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upgrade_imported_audiobook_api_imported_audiobooks__edition_id__upgrade_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                edition_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportedAudiobookResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_imports_api_imports_preview_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "multipart/form-data": components["schemas"]["Body_preview_imports_api_imports_preview_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportPreviewResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    book_info_api_library_books__book_id__info_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LibraryBookInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    groups_api_library_groups_get: {
        parameters: {
            query?: {
                audiobook?: ("available" | "none" | "playable" | "unplayable") | null;
                cursor?: string | null;
                genre?: string | null;
                group_by?: "series" | "universe";
                limit?: number | null;
                q?: string;
                review?: ("missing-series" | "refreshing" | "refresh-error") | null;
                sort_by?: "title" | "author" | "word_count" | "updated_at";
                sort_order?: "asc" | "desc";
                source?: ("web" | "epub" | "audiobook") | null;
                universe?: number | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LibraryGroup"][] | components["schemas"]["LibraryGroupsPage"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_membership_api_library_universe_membership_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UniverseMembership"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UniverseMembershipResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    universes_api_library_universes_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UniverseSummary"][];
                };
            };
        };
    };
    validate_library_api_library_validate_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LibraryValidation"];
                };
            };
        };
    };
    web_checks_api_library_web_checks_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WebCheck"][];
                };
            };
        };
    };
    get_lifecycle_definitions_api_lifecycles_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: components["schemas"]["LifecycleDefinition"];
                    };
                };
            };
        };
    };
    get_logs_api_logs_get: {
        parameters: {
            query?: {
                include_polling?: boolean;
                job_id?: number | null;
                level?: string | null;
                limit?: number;
                request_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LogEntry"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    post_client_log_api_logs_client_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ClientLogEntry"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OkResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    sync_metadata_apply_api_metadata_apply_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MetadataSyncApplyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetadataSyncApplyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_metadata_inbox_api_metadata_inbox_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetadataProposalSummary"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_metadata_job_api_metadata_jobs_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MetadataJobRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetadataSyncJob"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_latest_metadata_job_api_metadata_jobs_latest_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetadataSyncJob"] | null;
                };
            };
        };
    };
    approve_match_api_metadata_matches__match_id__approve_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                match_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetadataMatch"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reject_match_api_metadata_matches__match_id__reject_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                match_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetadataMatch"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    dismiss_proposal_api_metadata_proposals__proposal_id__dismiss_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                proposal_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetadataProposalSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    sync_metadata_preview_api_metadata_sync_preview_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MetadataSyncPreviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetadataSyncPreviewResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_diagnostics_api_observability_diagnostics_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/zip": Blob;
                };
            };
        };
    };
    get_health_api_observability_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthReport"];
                };
            };
        };
    };
    get_job_metrics_api_observability_job_metrics_get: {
        parameters: {
            query?: {
                window_hours?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobMetrics"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_readiness_api_observability_ready_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthReport"];
                };
            };
        };
    };
    list_processing_jobs_api_processing_jobs_get: {
        parameters: {
            query?: {
                book_id?: number | null;
                job_type?: string | null;
                limit?: number;
                /** @description Comma-separated statuses */
                statuses?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessingJob"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_processing_jobs_api_processing_jobs_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProcessingJobRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessingJobsCreated"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_processing_job_api_processing_jobs__job_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessingJob"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_processing_job_api_processing_jobs__job_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessingJob"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    retry_processing_job_api_processing_jobs__job_id__retry_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessingJob"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_reader_keys_api_reader_keys_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiKey"][];
                };
            };
        };
    };
    create_reader_key_api_reader_keys_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApiKeyCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiKeyWithToken"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    revoke_reader_key_api_reader_keys__key_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_recycle_bin_api_recycle_bin_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecycleBin"];
                };
            };
        };
    };
    permanently_delete_recycled_book_api_recycle_bin__book_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_recycled_book_api_recycle_bin__book_id__restore_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Book"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    purge_expired_recycled_books_api_recycle_bin_purge_expired_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PurgedBooks"];
                };
            };
        };
    };
    update_scheduler_config_api_scheduler_config_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SchedulerConfigUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SchedulerJobStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_scheduler_history_api_scheduler_history_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdateTask"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_task_logs_api_scheduler_history__task_id__logs_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BookLogWithTitle"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_scheduler_job_status_api_scheduler_job_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SchedulerJobStatus"];
                };
            };
        };
    };
    get_scheduler_status_api_scheduler_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdateTask"] | null;
                };
            };
        };
    };
    trigger_scheduler_api_scheduler_trigger_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SchedulerTriggered"];
                };
            };
        };
    };
    list_series_api_series_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": string[];
                };
            };
        };
    };
    rename_series_api_series__series_name__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                series_name: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SeriesRename"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeriesRenamed"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_series_genres_api_series__series_name__genres_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                series_name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeriesMetadataSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_series_genres_api_series__series_name__genres_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                series_name: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SeriesGenresUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeriesMetadataSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reorder_series_api_series__series_name__reorder_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                series_name: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SeriesReorder"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeriesReordered"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    merge_series_api_series_merge_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SeriesMerge"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeriesMerged"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cleanup_storage_api_storage_cleanup_post: {
        parameters: {
            query?: {
                dry_run?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StorageCleanup"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_check_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DatabaseHealth"];
                };
            };
        };
    };
    liveness_check_health_live_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StatusResponse"];
                };
            };
        };
    };
    readiness_check_health_ready_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthReport"];
                };
            };
        };
    };
    get_reader_book_reader_books__book_id__get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReaderBook"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reader_audiobook_chapter_audio_reader_books__book_id__audiobook_chapters__chapter_key__audio_get: {
        parameters: {
            query: {
                api_key?: string | null;
                version: number;
            };
            header?: never;
            path: {
                book_id: number;
                chapter_key: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "audio/mpeg": Blob;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reader_audiobook_chapter_smil_reader_books__book_id__audiobook_chapters__chapter_key__smil_get: {
        parameters: {
            query: {
                api_key?: string | null;
                version: number;
            };
            header?: never;
            path: {
                book_id: number;
                chapter_key: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/smil+xml": string;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reader_audiobook_manifest_reader_books__book_id__audiobook_manifest_get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReaderAudiobookManifest"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reader_audiobook_text_reader_books__book_id__audiobook_text_get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/epub+zip": Blob;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reader_download_book_reader_books__book_id__download_get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/epub+zip": Blob;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_reader_human_audiobooks_reader_books__book_id__human_audiobooks_get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportedAudiobookResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_reader_human_audiobook_chapters_reader_books__book_id__human_audiobooks_chapters_get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChapterResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_all_reader_books_reader_books_all_get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReaderBook"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_reader_standalone_books_reader_books_standalone_get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReaderBook"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reader_cover_reader_covers__book_id__get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path: {
                book_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "image/*": Blob;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_reader_human_audiobook_audio_reader_human_audiobooks__edition_id__tracks__track_id__audio_get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path: {
                edition_id: number;
                track_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "audio/*": Blob;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_reader_human_audiobook_smil_reader_human_audiobooks__edition_id__tracks__track_id__smil_get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path: {
                edition_id: number;
                track_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/smil+xml": string;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reader_opds_root_reader_opds_get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/atom+xml": string;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reader_opds_catalog_reader_opds_catalog_get: {
        parameters: {
            query?: {
                api_key?: string | null;
                page?: number;
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/atom+xml": string;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reader_opds_search_reader_opds_search_get: {
        parameters: {
            query?: {
                api_key?: string | null;
                q?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/atom+xml": string;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reader_opds_series_reader_opds_series_get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/atom+xml": string;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reader_opds_series_books_reader_opds_series__series_name__get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path: {
                series_name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/atom+xml": string;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_reader_series_reader_series_get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReaderSeriesSummary"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_reader_series_books_reader_series__series_name__books_get: {
        parameters: {
            query?: {
                api_key?: string | null;
            };
            header?: never;
            path: {
                series_name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReaderBook"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_reader_updates_reader_updates_get: {
        parameters: {
            query?: {
                api_key?: string | null;
                since?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReaderBook"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
