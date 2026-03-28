"""CRUD operations package — re-exports all functions for backward compatibility."""

from .books import (  # noqa: F401
    count_books,
    create_book,
    delete_all_books,
    delete_book,
    detach_book_source,
    get_book,
    get_book_by_source_url,
    get_book_by_title,
    get_book_by_title_and_author,
    get_book_catalog,
    get_books,
    get_books_by_author,
    get_books_by_ids,
    get_books_without_series,
    get_pending_web_books,
    get_web_books,
    search_books,
    touch_book_content,
    update_book,
)
from .series import (  # noqa: F401
    get_all_series,
    get_books_by_series,
    merge_series,
    rename_series,
    reorder_series_books,
)
from .logs import (  # noqa: F401
    complete_update_task,
    count_book_logs,
    create_book_log,
    create_update_task,
    fail_update_task,
    get_active_update_task,
    get_book_logs_for_task,
    get_latest_book_log,
    get_latest_update_task,
    get_update_tasks,
    increment_update_task,
    reset_stuck_update_tasks,
)
from .cleaning import (  # noqa: F401
    create_cleaning_config,
    delete_cleaning_config,
    get_all_matching_cleaning_configs,
    get_cleaning_config,
    get_cleaning_configs,
    get_matching_cleaning_config,
    update_cleaning_config,
)
from .reader import (  # noqa: F401
    get_all_reader_books,
    get_reader_book,
    get_reader_books,
    get_reader_books_by_series,
    get_reader_series,
    get_reader_standalone_books,
    get_reader_updates,
    search_reader_books,
)
from .api_keys import (  # noqa: F401
    create_api_key,
    get_api_keys,
    revoke_api_key,
)
