import { displayValue } from "../lib/errors";
import { parseLocation } from "../lib/navigation";
import { setNavigationGuard } from "../lib/navigationGuard";
import type { Book, BookSectionChange } from "../types";
import type { components } from "../api/schema";
import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import AudiobookPipeline from "./AudiobookPipeline";
import {
  getBook,
  getBookChapters,
  getBookCleanedChapters,
  getBookUpdateHistory,
} from "../api/books";
import { getMatchedConfigs, previewCleaning } from "../api/cleaning";
import { getSeries } from "../api/series";
import BookSettingsChapters from "./BookSettingsChapters";
import BookActionsSection from "./book-settings/BookActionsSection";
import {
  BookIdentifiersSection,
  ChapterUpdateHistory,
  SelectorPills,
  SourceTagList,
  SyncedGenreTagList,
} from "./book-settings/BookSettingsSections";
import CoverSection from "./book-settings/CoverSection";
import RecoverySection from "./book-settings/RecoverySection";
import SourceSection from "./book-settings/SourceSection";
import { useBookMutations } from "./book-settings/useBookMutations";
import { useBookSettingsForm } from "./book-settings/useBookSettingsForm";
import ConfirmActionDialog from "./ConfirmActionDialog";
import { queryKeys } from "../lib/queryKeys";

const fetchChapters = async ({
  queryKey,
  signal,
}: {
  queryKey: readonly [string, number, ...unknown[]];
  signal: AbortSignal;
}) => {
  const [_key, bookId] = queryKey;
  return getBookChapters(bookId, { signal });
};

const fetchCleanedChapters = async ({
  queryKey,
  signal,
}: {
  queryKey: readonly [string, number, ...unknown[]];
  signal: AbortSignal;
}) => {
  const [_key, bookId] = queryKey;
  return getBookCleanedChapters(bookId, { signal });
};

const fetchMatchedConfig = async ({
  queryKey,
  signal,
}: {
  queryKey: readonly [string, number, ...unknown[]];
  signal: AbortSignal;
}) => {
  const [_key, bookId] = queryKey;
  return getMatchedConfigs(bookId, { signal });
};

const fetchUpdateHistory = async ({
  queryKey,
  signal,
}: {
  queryKey: readonly [string, number, ...unknown[]];
  signal: AbortSignal;
}) => {
  const [_key, bookId] = queryKey;
  return getBookUpdateHistory(bookId, { signal });
};

function BookSettings({
  book: initialBook,
  onBack,
  bookSection,
  audiobookTab,
  onNavigationChange,
}: {
  book: Book;
  onBack: () => void;
  bookSection?: string | undefined;
  audiobookTab?: string | null | undefined;
  onNavigationChange?: BookSectionChange;
}) {
  // Poll the individual book while a refresh is in-flight so the UI reflects
  // backend state without the user navigating away. The query is seeded with
  // the book the parent passed so the page renders immediately; staleTime is
  // Infinity so we only hit the network when the refetchInterval fires or when
  // a mutation explicitly invalidates this key.
  const { data: polledBook } = useQuery({
    queryKey: queryKeys.books.detail(initialBook.id),
    queryFn: ({ signal }) => getBook(initialBook.id, { signal }),
    initialData: initialBook,
    staleTime: Infinity,
    refetchInterval: ({ state }) => {
      const current = state.data;
      if (!current || typeof current !== "object" || !current.id) return false;
      return current.refresh_status === "queued" ||
        current.refresh_status === "processing"
        ? 2000
        : false;
    },
  });

  // Guard against malformed responses (e.g., a test mock's catch-all): if the
  // polled value doesn't look like a book, fall back to the prop.
  const book =
    polledBook && typeof polledBook === "object" && polledBook.id
      ? polledBook
      : initialBook;
  const isRefreshing =
    book.refresh_status === "queued" || book.refresh_status === "processing";
  const refreshErrored = book.refresh_status === "error";

  const {
    title,
    setTitle,
    author,
    setAuthor,
    series,
    setSeries,
    seriesIndex,
    setSeriesIndex,
    notes,
    setNotes,
    isbn10,
    setIsbn10,
    isbn13,
    setIsbn13,
    asin,
    setAsin,
    googleBooksVolumeId,
    setGoogleBooksVolumeId,
    openLibraryWorkKey,
    setOpenLibraryWorkKey,
    openLibraryEditionKey,
    setOpenLibraryEditionKey,
    openLibraryAuthorKey,
    setOpenLibraryAuthorKey,
    otherRemoteIdsJson,
    setOtherRemoteIdsJson,
    identifierError,
    userGenreTags,
    setUserGenreTags,
    removedChapters,
    setRemovedChapters,
    contentSelectors,
    setContentSelectors,
    previewResult,
    setPreviewResult,
    chapterSearch,
    setChapterSearch,
    chaptersExpanded,
    setChaptersExpanded,
    chapterPreviewMode,
    setChapterPreviewMode,
    identifiersExpanded,
    setIdentifiersExpanded,
    getUpdatedFields,
    isDirty,
  } = useBookSettingsForm(initialBook);

  // Set once the book is deleted or detached, so leaving afterwards never asks
  // about edits that no longer matter.
  const leavingDeliberately = useRef(false);

  // Warn before a reload, tab close, or in-app navigation discards unsaved
  // edits. Switching between this book's settings sections keeps the form.
  useEffect(() => {
    if (!isDirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    const releaseGuard = setNavigationGuard((href) => {
      if (leavingDeliberately.current) return true;
      const target = new URL(href, window.location.origin);
      const next = parseLocation(target.pathname, target.hash, target.search);
      if (next.bookId === initialBook.id && next.bookSection !== "overview")
        return true;
      return window.confirm(
        "You have unsaved changes to this book. Discard them?",
      );
    });
    return () => {
      window.removeEventListener("beforeunload", warn);
      releaseGuard();
    };
  }, [isDirty, initialBook.id]);

  const leaveSettings = () => onBack();
  const [previewedChapter, setPreviewedChapter] = useState<string | null>(null);
  const [internalBookTab, setInternalBookTab] = useState("details");
  const bookTab = bookSection
    ? bookSection === "audiobooks"
      ? "audiobook"
      : "details"
    : internalBookTab;
  const setBookTab = (tab: string) => {
    if (onNavigationChange) {
      onNavigationChange(tab === "audiobook" ? "audiobooks" : "details");
    } else {
      setInternalBookTab(tab);
    }
  };
  const [jobNotice, setJobNotice] = useState("");
  const [confirmAction, setConfirmAction] = useState<{
    type: "delete" | "detach" | "original" | "revision";
    revision?: components["schemas"]["BookRevision"];
  } | null>(null);

  const { data: chapters = [], isLoading: chaptersLoading } = useQuery({
    queryKey: queryKeys.chapters(book.id),
    queryFn: fetchChapters,
    enabled: Boolean(book.immutable_path),
  });

  const { data: cleanedChapters = [], isLoading: cleanedChaptersLoading } =
    useQuery({
      queryKey: queryKeys.cleanedChapters(book.id),
      queryFn: fetchCleanedChapters,
      enabled: chapterPreviewMode === "cleaned" && Boolean(book.current_path),
    });

  const { data: matchedConfigs = [] } = useQuery({
    queryKey: queryKeys.matchedConfig(book.id),
    queryFn: fetchMatchedConfig,
  });

  const {
    data: updateHistory,
    isLoading: updateHistoryLoading,
    isError: updateHistoryIsError,
    error: updateHistoryError,
  } = useQuery({
    queryKey: queryKeys.bookUpdateHistory.version(
      book.id,
      book.content_version,
    ),
    queryFn: fetchUpdateHistory,
    enabled: book.source_type === "web",
    refetchInterval: isRefreshing ? 5000 : false,
  });

  const { data: allSeries = [] } = useQuery({
    queryKey: queryKeys.series,
    queryFn: getSeries,
    staleTime: 60_000,
  });

  const {
    save: saveMutation,
    enableAudiobook: enableAudiobookMutation,
    process: processMutation,
    refresh: refreshMutation,
    detachSource: detachSourceMutation,
    remove: deleteMutation,
    restoreOriginal: restoreOriginalMutation,
    restoreRevision: restoreRevisionMutation,
    metadataSync: metadataSyncMutation,
  } = useBookMutations(book.id, {
    onNotice: setJobNotice,
    onLeave: () => {
      leavingDeliberately.current = true;
      onBack();
    },
    onAudiobookEnabled: () => setBookTab("audiobook"),
    onRestored: () => setConfirmAction(null),
  });

  const previewMutation = useMutation({
    mutationFn: () =>
      previewCleaning(book.id, {
        content_selectors: contentSelectors,
        removed_chapters: removedChapters,
      }),
    onSuccess: (data) => setPreviewResult(data),
  });

  const handleSave = () => {
    const payload = getUpdatedFields();
    if (!payload) return;
    saveMutation.mutate(payload);
  };

  const handleProcess = async () => {
    try {
      const payload = getUpdatedFields();
      if (!payload) return;
      await saveMutation.mutateAsync(payload);
      await processMutation.mutateAsync();
    } catch (err) {
      console.error("Save or process failed", err);
    }
  };

  // Open a confirmation without a stale error from an earlier attempt.
  const openConfirmAction = (action: NonNullable<typeof confirmAction>) => {
    deleteMutation.reset();
    detachSourceMutation.reset();
    restoreOriginalMutation.reset();
    restoreRevisionMutation.reset();
    setConfirmAction(action);
  };

  const toggleChapter = (filename: string) => {
    setRemovedChapters((prev) =>
      prev.includes(filename)
        ? prev.filter((f) => f !== filename)
        : [...prev, filename],
    );
  };

  const toggleChapterPreview = (filename: string) => {
    setPreviewedChapter((prev) => (prev === filename ? null : filename));
  };

  const isBusy =
    saveMutation.isPending ||
    processMutation.isPending ||
    refreshMutation.isPending ||
    detachSourceMutation.isPending ||
    deleteMutation.isPending ||
    restoreOriginalMutation.isPending ||
    restoreRevisionMutation.isPending ||
    enableAudiobookMutation.isPending ||
    isRefreshing;

  return (
    <div
      className={`book-settings${
        bookTab === "audiobook" ? " book-settings--wide" : ""
      }`}
    >
      <nav className="breadcrumbs" aria-label="Book location">
        <button
          className="btn-text"
          onClick={leaveSettings}
          disabled={
            saveMutation.isPending ||
            processMutation.isPending ||
            refreshMutation.isPending ||
            detachSourceMutation.isPending ||
            deleteMutation.isPending ||
            enableAudiobookMutation.isPending
          }
        >
          ← Back to library
        </button>
        {onNavigationChange && (
          <>
            <span aria-hidden="true">/</span>
            <a href={`/books/${book.id}/overview`}>{book.title}</a>
          </>
        )}
        <span aria-hidden="true">/</span>
        <span>{bookTab === "audiobook" ? "Audiobooks" : "Details"}</span>
      </nav>
      <div className="settings-header">
        <div className="settings-title-block">
          <h2>{book.title}</h2>
          <span>{book.author || "Unknown author"}</span>
        </div>
      </div>
      <nav className="book-settings-tabs">
        <button
          className={`book-settings-tab${bookTab === "details" ? " book-settings-tab--active" : ""}`}
          onClick={() => setBookTab("details")}
        >
          Details
        </button>
        <button
          className={`book-settings-tab${bookTab === "audiobook" ? " book-settings-tab--active" : ""}`}
          onClick={() => setBookTab("audiobook")}
        >
          Audiobooks
        </button>
      </nav>

      {bookTab === "audiobook" && (
        <AudiobookPipeline
          book={book}
          onEnableAi={() => enableAudiobookMutation.mutate()}
          audiobookTab={audiobookTab ?? undefined}
          onAudiobookTabChange={(tab) =>
            onNavigationChange?.("audiobooks", tab)
          }
        />
      )}

      {bookTab === "details" && (
        <>
          {isRefreshing && (
            <div
              className="hint"
              role="status"
              style={{ marginBottom: "0.75rem" }}
            >
              {book.refresh_status === "queued"
                ? "This book is queued for refresh. It will start once the previous job finishes."
                : "Refreshing from source — pulling new chapters via FanFicFare. This can take a few minutes for long stories."}
            </div>
          )}
          {refreshErrored && (
            <p className="error" role="alert">
              The last refresh attempt failed. Check the logs, then click
              “Refresh from Source” to try again.
            </p>
          )}

          <section className="settings-section">
            <h3>Metadata</h3>
            <div className="settings-row-with-cover">
              <div className="settings-fields">
                <label>
                  Title
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </label>
                <label>
                  Author
                  <input
                    value={author}
                    onChange={(e) => setAuthor(e.target.value)}
                  />
                </label>
                <div className="field-row">
                  <label className="field-row-grow">
                    Series
                    <input
                      list="series-options"
                      value={series}
                      onChange={(e) => setSeries(e.target.value)}
                      placeholder="Leave blank if none"
                    />
                    <datalist id="series-options">
                      {allSeries.map((s) => (
                        <option key={s} value={s} />
                      ))}
                    </datalist>
                  </label>
                  <label className="field-row-shrink">
                    Order
                    <input
                      type="number"
                      step="0.01"
                      value={seriesIndex}
                      onChange={(e) => setSeriesIndex(e.target.value)}
                      placeholder="e.g. 2.5"
                    />
                  </label>
                </div>
                <div className="settings-tag-field">
                  <span className="settings-field-label">
                    Synced Genre Tags
                  </span>
                  <SyncedGenreTagList tags={book.genre_tags || []} />
                </div>
                {(book.source_tags || []).length > 0 && (
                  <div className="settings-tag-field">
                    <span className="settings-field-label">Source Tags</span>
                    <SourceTagList tags={book.source_tags || []} />
                  </div>
                )}
                {book.metadata_details &&
                  Object.keys(book.metadata_details).length > 0 && (
                    <div className="metadata-details">
                      <span className="settings-field-label">
                        Online Details
                      </span>
                      <dl>
                        {displayValue(book.metadata_details.publisher) && (
                          <>
                            <dt>Publisher</dt>
                            <dd>
                              {displayValue(book.metadata_details.publisher)}
                            </dd>
                          </>
                        )}
                        {displayValue(book.metadata_details.published_date) && (
                          <>
                            <dt>Published</dt>
                            <dd>
                              {displayValue(
                                book.metadata_details.published_date,
                              )}
                            </dd>
                          </>
                        )}
                        {displayValue(book.metadata_details.language) && (
                          <>
                            <dt>Language</dt>
                            <dd>
                              {displayValue(book.metadata_details.language)}
                            </dd>
                          </>
                        )}
                        {displayValue(book.metadata_details.page_count) && (
                          <>
                            <dt>Pages</dt>
                            <dd>
                              {displayValue(book.metadata_details.page_count)}
                            </dd>
                          </>
                        )}
                        {displayValue(book.metadata_details.amazon_rating) && (
                          <>
                            <dt>Amazon rating</dt>
                            <dd>
                              {displayValue(
                                book.metadata_details.amazon_rating,
                              )}
                              /5
                              {displayValue(
                                book.metadata_details.amazon_review_count,
                              )
                                ? ` (${displayValue(book.metadata_details.amazon_review_count)?.toLocaleString()} reviews)`
                                : ""}
                            </dd>
                          </>
                        )}
                      </dl>
                      {displayValue(book.metadata_details.description) && (
                        <p className="hint metadata-description">
                          {displayValue(book.metadata_details.description)}
                        </p>
                      )}
                    </div>
                  )}
                <label>
                  User Genre Tags
                  <input
                    value={userGenreTags}
                    onChange={(e) => setUserGenreTags(e.target.value)}
                    placeholder="Fantasy, Romance, LitRPG"
                  />
                </label>
                {book.metadata_synced_at && (
                  <p className="hint">
                    Synced from {book.metadata_sync_source || "online metadata"}{" "}
                    on {new Date(book.metadata_synced_at).toLocaleString()}.
                  </p>
                )}
                <div className="settings-actions">
                  <button
                    type="button"
                    onClick={() => metadataSyncMutation.mutate()}
                    disabled={metadataSyncMutation.isPending}
                  >
                    {metadataSyncMutation.isPending
                      ? "Queueing…"
                      : "Recheck Online Metadata"}
                  </button>
                </div>
                {metadataSyncMutation.isSuccess && (
                  <p className="hint" role="status">
                    Metadata recheck queued.
                  </p>
                )}
                {metadataSyncMutation.isError && (
                  <p className="error" role="alert">
                    Metadata recheck failed:{" "}
                    {metadataSyncMutation.error.message}
                  </p>
                )}
              </div>
              <CoverSection book={book} onNotice={setJobNotice} />
            </div>
          </section>

          {!book.audiobook_enabled && (
            <section className="settings-section">
              <h3>Audiobook</h3>
              <p className="hint">
                Import an audiobook or generate AI narration for this book.
              </p>
              <div className="settings-actions">
                <button type="button" onClick={() => setBookTab("audiobook")}>
                  Import Existing Audiobook
                </button>
                <button
                  type="button"
                  onClick={() => enableAudiobookMutation.mutate()}
                  disabled={enableAudiobookMutation.isPending}
                >
                  {enableAudiobookMutation.isPending
                    ? "Enabling…"
                    : "Enable AI narration"}
                </button>
              </div>
              {enableAudiobookMutation.isError && (
                <p className="error" role="alert">
                  {enableAudiobookMutation.error?.message ||
                    "Could not enable AI narration"}
                </p>
              )}
            </section>
          )}

          <section className="settings-section">
            <h3>Notes</h3>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Personal notes about this book"
              rows={3}
            />
          </section>

          {(book.source_url || book.source_type === "web") && (
            <SourceSection
              book={book}
              disabled={isBusy}
              isDetaching={detachSourceMutation.isPending}
              onDetach={() => openConfirmAction({ type: "detach" })}
            />
          )}

          {book.source_type === "web" && (
            <ChapterUpdateHistory
              updateHistory={updateHistory}
              isLoading={updateHistoryLoading}
              isError={updateHistoryIsError}
              error={updateHistoryError}
            />
          )}

          <BookIdentifiersSection
            identifiersExpanded={identifiersExpanded}
            setIdentifiersExpanded={setIdentifiersExpanded}
            isbn10={isbn10}
            setIsbn10={setIsbn10}
            isbn13={isbn13}
            setIsbn13={setIsbn13}
            asin={asin}
            setAsin={setAsin}
            googleBooksVolumeId={googleBooksVolumeId}
            setGoogleBooksVolumeId={setGoogleBooksVolumeId}
            openLibraryWorkKey={openLibraryWorkKey}
            setOpenLibraryWorkKey={setOpenLibraryWorkKey}
            openLibraryEditionKey={openLibraryEditionKey}
            setOpenLibraryEditionKey={setOpenLibraryEditionKey}
            openLibraryAuthorKey={openLibraryAuthorKey}
            setOpenLibraryAuthorKey={setOpenLibraryAuthorKey}
            otherRemoteIdsJson={otherRemoteIdsJson}
            setOtherRemoteIdsJson={setOtherRemoteIdsJson}
            identifierError={identifierError}
          />

          {matchedConfigs.map((cfg) => (
            <section key={cfg.id} className="settings-section">
              <h3>
                Inherited Cleaning Rules{" "}
                <span className="badge-config">{cfg.name}</span>
              </h3>
              <p className="hint">
                These site-wide rules apply automatically and cannot be edited
                here.
              </p>
              {(cfg.chapter_selectors?.length ?? 0) > 0 && (
                <div>
                  <strong>Chapter selectors:</strong>
                  <div className="pills readonly">
                    {(cfg.chapter_selectors || []).map((s) => (
                      <span key={s} className="pill">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {(cfg.content_selectors?.length ?? 0) > 0 && (
                <div>
                  <strong>Content selectors:</strong>
                  <div className="pills readonly">
                    {(cfg.content_selectors || []).map((s) => (
                      <span key={s} className="pill">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </section>
          ))}

          <section className="settings-section">
            <h3>Per-Book Content Selectors</h3>
            <p className="hint">
              CSS selectors for content to remove from this book only.
            </p>
            <SelectorPills
              selectors={contentSelectors}
              onChange={setContentSelectors}
            />
            <div
              style={{
                marginTop: "0.5rem",
                display: "flex",
                alignItems: "center",
                gap: "1rem",
              }}
            >
              <button
                onClick={() => previewMutation.mutate()}
                disabled={previewMutation.isPending}
              >
                {previewMutation.isPending ? "Previewing..." : "Preview"}
              </button>
              {previewResult && (
                <span className="hint">
                  Would remove {previewResult.elements_removed} elements · ~
                  {previewResult.estimated_word_count.toLocaleString()} words
                  remaining
                </span>
              )}
              {previewMutation.isError && (
                <span className="error" role="alert">
                  {previewMutation.error.message}
                </span>
              )}
            </div>
          </section>

          <BookSettingsChapters
            book={book}
            chapters={chapters}
            cleanedChapters={cleanedChapters}
            chaptersLoading={chaptersLoading}
            cleanedChaptersLoading={cleanedChaptersLoading}
            chaptersExpanded={chaptersExpanded}
            setChaptersExpanded={setChaptersExpanded}
            chapterPreviewMode={chapterPreviewMode}
            setChapterPreviewMode={setChapterPreviewMode}
            chapterSearch={chapterSearch}
            setChapterSearch={setChapterSearch}
            removedChapters={removedChapters}
            toggleChapter={toggleChapter}
            previewedChapter={previewedChapter}
            toggleChapterPreview={toggleChapterPreview}
          />

          <RecoverySection
            book={book}
            disabled={isBusy}
            onRestoreOriginal={() => openConfirmAction({ type: "original" })}
            onRestoreRevision={(revision) =>
              openConfirmAction({ type: "revision", revision })
            }
          />

          <BookActionsSection
            book={book}
            disabled={isBusy}
            saving={saveMutation.isPending}
            processing={processMutation.isPending}
            refreshing={refreshMutation.isPending}
            jobNotice={jobNotice}
            onSave={handleSave}
            onProcess={() => {
              void handleProcess();
            }}
            onRefresh={() => refreshMutation.mutate()}
            onDelete={() => openConfirmAction({ type: "delete" })}
          />

          {saveMutation.isError && (
            <p className="error" role="alert">
              Save failed: {saveMutation.error.message}
            </p>
          )}
          {processMutation.isError && (
            <p className="error" role="alert">
              Process failed: {processMutation.error.message}
            </p>
          )}
          {refreshMutation.isError && (
            <p className="error" role="alert">
              Refresh failed: {refreshMutation.error.message}
            </p>
          )}

          <ConfirmActionDialog
            open={confirmAction?.type === "delete"}
            title={`Move “${book.title}” to the recycle bin?`}
            confirmLabel="Move to recycle bin"
            busyLabel="Moving…"
            danger
            isPending={deleteMutation.isPending}
            onCancel={() => setConfirmAction(null)}
            onConfirm={() => deleteMutation.mutate()}
          >
            <p>
              The book disappears from the library, but its EPUB, cover,
              audiobook files, and history are preserved.
            </p>
            <p>
              You can restore it from Library Tools during the configured
              recovery window (30 days by default). Permanent deletion remains
              available there.
            </p>
            {deleteMutation.isError && (
              <p className="error" role="alert">
                Delete failed: {deleteMutation.error.message}
              </p>
            )}
          </ConfirmActionDialog>

          <ConfirmActionDialog
            open={confirmAction?.type === "detach"}
            title={`Remove the web source from “${book.title}”?`}
            confirmLabel="Remove web source"
            isPending={detachSourceMutation.isPending}
            onCancel={() => setConfirmAction(null)}
            onConfirm={() => detachSourceMutation.mutate()}
          >
            <p>
              The EPUB files stay in your library, but source refreshes stop and
              the book becomes EPUB-only.
            </p>
            {detachSourceMutation.isError && (
              <p className="error" role="alert">
                Convert to EPUB-only failed:{" "}
                {detachSourceMutation.error.message}
              </p>
            )}
          </ConfirmActionDialog>

          <ConfirmActionDialog
            open={confirmAction?.type === "original"}
            title="Restore the original EPUB?"
            confirmLabel="Restore original"
            isPending={restoreOriginalMutation.isPending}
            onCancel={() => setConfirmAction(null)}
            onConfirm={() => restoreOriginalMutation.mutate()}
          >
            <p>
              This replaces the current readable EPUB with the immutable
              original and clears this book’s chapter removals and content
              selectors.
            </p>
            <p>
              Your metadata and the immutable original are not changed. The
              current state is saved in history first.
            </p>
            {restoreOriginalMutation.isError && (
              <p className="error" role="alert">
                Restore failed: {restoreOriginalMutation.error.message}
              </p>
            )}
          </ConfirmActionDialog>

          <ConfirmActionDialog
            open={confirmAction?.type === "revision"}
            title="Restore this saved revision?"
            confirmLabel="Restore revision"
            isPending={restoreRevisionMutation.isPending}
            onCancel={() => setConfirmAction(null)}
            onConfirm={() => {
              if (confirmAction?.revision)
                restoreRevisionMutation.mutate(confirmAction.revision.id);
            }}
          >
            <p>{confirmAction?.revision?.summary}</p>
            <p>
              The current metadata and cleaning settings are saved as a new
              revision before the rollback.
            </p>
            {restoreRevisionMutation.isError && (
              <p className="error" role="alert">
                Restore failed: {restoreRevisionMutation.error.message}
              </p>
            )}
          </ConfirmActionDialog>
        </>
      )}
    </div>
  );
}

export default BookSettings;
