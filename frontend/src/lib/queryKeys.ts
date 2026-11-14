import type { QueryClient } from "@tanstack/react-query";

// Every query key the app uses. A scope's `all` key prefix-matches its more
// specific keys, so invalidating `all` refreshes every variant of that view.
export const queryKeys = {
  activeProcessingJobs: ["active-processing-jobs"] as const,
  processingJobs: {
    all: ["processing-jobs"] as const,
    list: (statuses: string) => ["processing-jobs", statuses] as const,
  },
  processingBookCatalog: (operation: string, search: string) =>
    ["processing-book-catalog", operation, search] as const,
  attentionDashboard: ["attention-dashboard"] as const,
  notificationWebhooks: ["notification-webhooks"] as const,
  attentionActionJob: (jobId: number) =>
    ["attention-action-job", jobId] as const,

  books: {
    all: ["book"] as const,
    detail: (bookId: number | null | undefined) => ["book", bookId] as const,
  },
  bookCatalog: {
    all: ["book-catalog"] as const,
    list: (params: object) => ["book-catalog", params] as const,
  },
  importBookCatalog: ["import-book-catalog"] as const,
  libraryGroups: {
    all: ["library-groups"] as const,
    list: (params: object) => ["library-groups", params] as const,
  },
  libraryBookInfo: {
    all: ["library-book-info"] as const,
    detail: (bookId: number) => ["library-book-info", bookId] as const,
  },
  series: ["series"] as const,
  seriesBooks: {
    all: ["series-books"] as const,
    list: (series: string) => ["series-books", series] as const,
  },
  universes: ["universes"] as const,
  webUpdateBooks: ["web-update-books"] as const,

  chapters: (bookId: number) => ["chapters", bookId] as const,
  cleanedChapters: (bookId: number) => ["cleaned-chapters", bookId] as const,
  matchedConfig: (bookId: number) => ["matched-config", bookId] as const,
  bookRevisions: (bookId: number) => ["book-revisions", bookId] as const,
  bookUpdateHistory: {
    all: (bookId: number) => ["book-update-history", bookId] as const,
    version: (bookId: number, contentVersion: number | null | undefined) =>
      ["book-update-history", bookId, contentVersion] as const,
  },

  cleaningConfigs: ["cleaning-configs"] as const,
  reprocessAllStatus: ["reprocess-all-status"] as const,
  recycleBin: ["recycle-bin"] as const,
  backups: ["backups"] as const,
  backupJobs: ["backup-jobs"] as const,
  metadataInbox: {
    all: ["metadata-inbox"] as const,
    page: (page: number) => ["metadata-inbox", page] as const,
  },
  metadataJobLatest: ["metadata-job-latest"] as const,
  humanAudiobookRebuildPreview: ["human-audiobook-rebuild-preview"] as const,

  schedulerStatus: ["scheduler-status"] as const,
  schedulerJob: ["scheduler-job"] as const,
  schedulerHistory: ["scheduler-history"] as const,
  schedulerLatestRun: ["scheduler-history", "latest"] as const,
  taskLogs: (taskId: number) => ["task-logs", taskId] as const,
  webUpdateSchedule: ["web-update-schedule"] as const,
  webChecks: ["web-checks"] as const,

  observabilityHealth: ["observability-health"] as const,
  observabilityJobMetrics: ["observability-job-metrics"] as const,
  logs: (level: string) => ["logs", level] as const,
  lifecycleDefinitions: ["lifecycle-definitions"] as const,

  audiobook: {
    settings: ["audiobook-settings"] as const,
    endpointStats: ["audiobook-endpoint-stats"] as const,
    status: (bookId: number) => ["audiobook-status", bookId] as const,
    characters: (bookId: number) => ["audiobook-characters", bookId] as const,
    chapters: (bookId: number) => ["audiobook-chapters", bookId] as const,
    imports: (bookId: number) => ["audiobook-imports", bookId] as const,
    sentences: {
      all: (bookId: number) => ["audiobook-sentences", bookId] as const,
      page: (
        bookId: number,
        page: number,
        chapterFilter: string,
        reviewOnly: boolean,
      ) =>
        [
          "audiobook-sentences",
          bookId,
          page,
          chapterFilter,
          reviewOnly,
        ] as const,
    },
    readerSentences: (bookId: number, chapterId: number | null) =>
      ["audiobook-reader-sentences", bookId, chapterId] as const,
    importedCues: (
      editionId: number,
      trackId: number | null,
      alignment: number | string,
    ) => ["imported-audiobook-cues", editionId, trackId, alignment] as const,
  },
};

// Refresh every list and summary that shows a book after it changes: catalog
// pages, library groups, series lists and the series index, and the book's
// info panel.
export function invalidateBookViews(client: QueryClient, bookId?: number) {
  for (const queryKey of [
    queryKeys.bookCatalog.all,
    queryKeys.libraryGroups.all,
    queryKeys.seriesBooks.all,
    queryKeys.series,
    bookId == null
      ? queryKeys.libraryBookInfo.all
      : queryKeys.libraryBookInfo.detail(bookId),
  ])
    void client.invalidateQueries({ queryKey });
}
