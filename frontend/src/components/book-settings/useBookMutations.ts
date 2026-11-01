import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { components } from "../../api/schema";
import {
  deleteBook,
  detachBookSource,
  processBook,
  refreshBook,
  restoreBookRevision,
  restoreOriginalEpub,
  updateBook,
} from "../../api/books";
import { queueMetadataSync } from "../../api/metadata";
import { invalidateBookViews, queryKeys } from "../../lib/queryKeys";
import type { Book } from "../../types";

type BookMutationCallbacks = {
  // A background job was queued, or a change finished, worth telling the user.
  onNotice: (message: string) => void;
  // The book was deleted or lost its source; the settings page should close.
  onLeave: () => void;
  onAudiobookEnabled: () => void;
  onRestored: () => void;
};

// Every book-level write on the settings page. Each success refreshes the
// views that show this book and keeps the cached book detail current.
export function useBookMutations(
  bookId: number,
  { onNotice, onLeave, onAudiobookEnabled, onRestored }: BookMutationCallbacks,
) {
  const queryClient = useQueryClient();
  const storeBook = (updatedBook: Book) => {
    queryClient.setQueryData(queryKeys.books.detail(bookId), updatedBook);
    invalidateBookViews(queryClient, bookId);
  };
  const invalidate = (queryKey: readonly unknown[]) =>
    void queryClient.invalidateQueries({ queryKey });

  const save = useMutation({
    mutationFn: (data: components["schemas"]["BookUpdate"]) =>
      updateBook(bookId, data),
    onSuccess: storeBook,
  });

  const enableAudiobook = useMutation({
    mutationFn: () => updateBook(bookId, { audiobook_enabled: true }),
    onSuccess: (updatedBook) => {
      storeBook(updatedBook);
      onAudiobookEnabled();
    },
  });

  const process = useMutation({
    mutationFn: () => processBook(bookId),
    onSuccess: () => {
      onNotice("EPUB cleaning job queued.");
      invalidateBookViews(queryClient, bookId);
      invalidate(queryKeys.cleanedChapters(bookId));
    },
  });

  // Queues an async refresh and returns immediately; the book detail query
  // polls until refresh_status clears so the page shows progress in place.
  const refresh = useMutation({
    mutationFn: () => refreshBook(bookId),
    onSuccess: (updatedBook) => {
      onNotice("Source refresh job queued.");
      storeBook(updatedBook);
      invalidate(queryKeys.bookUpdateHistory.all(bookId));
    },
  });

  const detachSource = useMutation({
    mutationFn: () => detachBookSource(bookId),
    onSuccess: () => {
      invalidateBookViews(queryClient, bookId);
      onLeave();
    },
  });

  const remove = useMutation({
    mutationFn: () => deleteBook(bookId),
    onSuccess: () => {
      invalidateBookViews(queryClient, bookId);
      onLeave();
    },
  });

  const restoreOriginal = useMutation({
    mutationFn: () => restoreOriginalEpub(bookId),
    onSuccess: (updatedBook) => {
      onRestored();
      onNotice("Original EPUB restored.");
      storeBook(updatedBook);
      invalidate(queryKeys.bookRevisions(bookId));
      invalidate(queryKeys.chapters(bookId));
      invalidate(queryKeys.cleanedChapters(bookId));
    },
  });

  const restoreRevision = useMutation({
    mutationFn: (revisionId: number) => restoreBookRevision(bookId, revisionId),
    onSuccess: (updatedBook) => {
      onRestored();
      storeBook(updatedBook);
      invalidate(queryKeys.bookRevisions(bookId));
    },
  });

  const metadataSync = useMutation({
    mutationFn: () => queueMetadataSync([bookId], "manual"),
  });

  return {
    save,
    enableAudiobook,
    process,
    refresh,
    detachSource,
    remove,
    restoreOriginal,
    restoreRevision,
    metadataSync,
  };
}
