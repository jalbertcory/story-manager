import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getBookCatalog } from "../api/books";
import useDebouncedValue from "../hooks/useDebouncedValue";
import useLifecycleDefinitions from "../hooks/useLifecycleDefinitions";
import {
  cancelProcessingJob,
  getProcessingJobs,
  queueProcessingJobs,
  retryProcessingJob,
} from "../api/processing";

const JOB_LABELS = {
  clean_book: "Clean book",
  clean_all: "Clean library",
  refresh_book: "Refresh book",
  refresh_all: "Refresh web library",
  audiobook_pipeline: "Generate AI audiobook",
  import_audiobook: "Import human audiobook",
  rematch_imported_audiobook: "Rematch human audiobook",
  align_imported_audiobook: "Align human audiobook",
  metadata_sync: "Sync metadata",
  generate_sentence_audio: "Generate sentence audio",
  generate_chapter_preview: "Generate chapter preview",
  retry_cover: "Re-extract book cover",
  create_backup: "Create library backup",
  verify_backup: "Verify library backup",
};

const QUEUE_OPERATIONS = [
  { value: "clean_book", label: "Clean selected books" },
  { value: "audiobook_pipeline", label: "Regenerate selected AI audiobooks" },
  { value: "refresh_book", label: "Refresh selected web books" },
];

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : "—";
}

function JobProgress({ job, runningState }) {
  const measured = job.progress_total > 0;
  if (!measured && job.status !== runningState) return null;

  const percent = measured
    ? Math.min(
        100,
        Math.round((job.progress_current * 100) / job.progress_total),
      )
    : null;

  return (
    <div
      className={`processing-job-progress${measured ? "" : " processing-job-progress--indeterminate"}`}
    >
      <progress
        aria-label={`${JOB_LABELS[job.job_type] || job.job_type} progress`}
        {...(measured
          ? { value: job.progress_current, max: job.progress_total }
          : {})}
      />
      <span>
        {measured
          ? `${percent}% · ${job.progress_current} / ${job.progress_total}`
          : "In progress"}
      </span>
    </div>
  );
}

function ProcessingJobs() {
  const queryClient = useQueryClient();
  const { data: lifecycleDefinitions } = useLifecycleDefinitions();
  const processingLifecycle = lifecycleDefinitions?.processing_job;
  const activeStatuses = useMemo(
    () => new Set(processingLifecycle?.active_states ?? []),
    [processingLifecycle],
  );
  const retryableStatuses = useMemo(
    () => new Set(processingLifecycle?.retryable_states ?? []),
    [processingLifecycle],
  );
  const statusLabels = useMemo(
    () =>
      Object.fromEntries(
        (processingLifecycle?.states ?? []).map((state) => [
          state.value,
          state.label,
        ]),
      ),
    [processingLifecycle],
  );
  const [statusFilter, setStatusFilter] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get("status");
    return requested || "active";
  });
  const [operation, setOperation] = useState("clean_book");
  const [bookSearch, setBookSearch] = useState("");
  const debouncedBookSearch = useDebouncedValue(bookSearch.trim(), 250);
  const [selectedIds, setSelectedIds] = useState([]);
  const [queueNotice, setQueueNotice] = useState("");
  const statuses =
    statusFilter === "active"
      ? (processingLifecycle?.active_states ?? []).join(",")
      : statusFilter === "all"
        ? ""
        : statusFilter;

  const {
    data: jobs = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["processing-jobs", statuses],
    queryFn: () => getProcessingJobs({ statuses, limit: 200 }),
    enabled: Boolean(processingLifecycle),
    refetchInterval: ({ state }) =>
      state.data?.some((job) => activeStatuses.has(job.status)) ? 1500 : 5000,
  });
  const { data: catalogPage } = useQuery({
    queryKey: ["processing-book-catalog", operation, debouncedBookSearch],
    queryFn: () =>
      getBookCatalog({
        q: debouncedBookSearch,
        view: operation === "refresh_book" ? "web" : "all",
        sortBy: "title",
        sortOrder: "asc",
        limit: 100,
      }),
    staleTime: 30_000,
  });
  const catalog = useMemo(() => catalogPage?.items ?? [], [catalogPage]);

  const eligibleBooks = useMemo(() => {
    const query = debouncedBookSearch.toLocaleLowerCase();
    return catalog.filter((book) => {
      if (operation === "refresh_book" && book.source_type !== "web")
        return false;
      if (operation === "audiobook_pipeline" && !book.audiobook_enabled)
        return false;
      return (
        !query ||
        `${book.title} ${book.author}`.toLocaleLowerCase().includes(query)
      );
    });
  }, [catalog, debouncedBookSearch, operation]);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["processing-jobs"] });
    queryClient.invalidateQueries({ queryKey: ["active-processing-jobs"] });
  };
  const queueMutation = useMutation({
    mutationFn: ({ jobType, bookIds, payload }) =>
      queueProcessingJobs(jobType, bookIds, payload),
    onSuccess: (data) => {
      const count = data.jobs?.length || 0;
      setQueueNotice(
        `${count} processing job${count === 1 ? "" : "s"} queued.`,
      );
      setSelectedIds([]);
      refresh();
    },
  });
  const retryMutation = useMutation({
    mutationFn: retryProcessingJob,
    onSuccess: refresh,
  });
  const cancelMutation = useMutation({
    mutationFn: cancelProcessingJob,
    onSuccess: refresh,
  });

  const toggleBook = (bookId) => {
    setSelectedIds((current) =>
      current.includes(bookId)
        ? current.filter((id) => id !== bookId)
        : [...current, bookId],
    );
  };
  const queueSelected = () => {
    const payload =
      operation === "audiobook_pipeline" ? { mode: "reconcile" } : {};
    queueMutation.mutate({ jobType: operation, bookIds: selectedIds, payload });
  };

  const runningState = processingLifecycle?.groups?.running?.[0];
  const queuedState = processingLifecycle?.groups?.waiting?.[0];
  const runningCount = jobs.filter((job) => job.status === runningState).length;
  const queuedCount = jobs.filter((job) => job.status === queuedState).length;

  return (
    <div className="processing-page">
      <header className="processing-console-header">
        <div>
          <span>PRODUCTION CONSOLE</span>
          <h2>Processing control</h2>
        </div>
        <p>Durable work queue · automatic recovery enabled</p>
      </header>
      <div
        className="processing-health-strip"
        aria-label="Processing system status"
      >
        <div>
          <span className="processing-health-dot" />
          <strong>Queue online</strong>
          <small>Workers available</small>
        </div>
        <div>
          <strong>{runningCount} running</strong>
          <small>{queuedCount} waiting</small>
        </div>
      </div>
      <details className="settings-section processing-queue-panel">
        <summary className="processing-queue-summary">
          <span className="processing-queue-summary-heading">
          <span className="processing-section-code">01 / DISPATCH</span>
            <span className="processing-queue-title">Queue work</span>
          </span>
          <span className="hint">
            Queue cleaning, source refreshes, or audiobook regeneration for one
            or more books.
          </span>
        </summary>
        <div className="processing-quick-actions">
          <button
            onClick={() =>
              queueMutation.mutate({
                jobType: "clean_all",
                bookIds: [],
                payload: {},
              })
            }
            disabled={queueMutation.isPending}
          >
            Clean entire library
          </button>
          <button
            onClick={() =>
              queueMutation.mutate({
                jobType: "refresh_all",
                bookIds: [],
                payload: { trigger: "manual" },
              })
            }
            disabled={queueMutation.isPending}
          >
            Refresh all web books
          </button>
        </div>
        <div className="processing-book-picker">
          <label>
            Action
            <select
              value={operation}
              onChange={(event) => {
                setOperation(event.target.value);
                setSelectedIds([]);
              }}
            >
              {QUEUE_OPERATIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Find books
            <input
              value={bookSearch}
              onChange={(event) => setBookSearch(event.target.value)}
              placeholder="Title or author"
            />
          </label>
          <div className="processing-picker-actions">
            <button
              className="btn-text"
              onClick={() =>
                setSelectedIds(eligibleBooks.map((book) => book.id))
              }
              disabled={!eligibleBooks.length}
            >
              Select visible
            </button>
            <button
              className="btn-text"
              onClick={() => setSelectedIds([])}
              disabled={!selectedIds.length}
            >
              Clear
            </button>
          </div>
          <div
            className="processing-book-options"
            role="group"
            aria-label="Books to process"
          >
            {eligibleBooks.slice(0, 100).map((book) => (
              <label key={book.id}>
                <input
                  type="checkbox"
                  checked={selectedIds.includes(book.id)}
                  onChange={() => toggleBook(book.id)}
                />
                <span>
                  <strong>{book.title}</strong>
                  <small>{book.author}</small>
                </span>
              </label>
            ))}
            {!eligibleBooks.length && (
              <p className="hint">No eligible books match.</p>
            )}
          </div>
          <button
            className="btn-primary"
            onClick={queueSelected}
            disabled={!selectedIds.length || queueMutation.isPending}
          >
            {queueMutation.isPending
              ? "Queueing…"
              : selectedIds.length
                ? `Queue ${selectedIds.length} selected`
                : "Queue selected"}
          </button>
        </div>
        {queueNotice && <p className="job-queued-notice">{queueNotice}</p>}
        {queueMutation.isError && (
          <p className="error">{queueMutation.error.message}</p>
        )}
      </details>

      <section className="settings-section">
        <div className="processing-list-header">
          <div>
            <span className="processing-section-code">02 / JOB LEDGER</span>
            <h2>Processing jobs</h2>
            <p className="hint">
              Durable work survives application restarts and can be retried
              here.
            </p>
          </div>
          <label>
            Status
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              <option value="active">Active</option>
              <option value="all">All</option>
              {(processingLifecycle?.terminal_states ?? []).map((value) => (
                <option key={value} value={value}>
                  {statusLabels[value] ?? value}
                </option>
              ))}
            </select>
          </label>
        </div>
        {isLoading && <p>Loading jobs…</p>}
        {error && <p className="error">{error.message}</p>}
        {!isLoading && !jobs.length && (
          <p className="hint">No processing jobs in this view.</p>
        )}
        <div className="processing-job-list">
          {jobs.map((job) => (
            <article
              key={job.id}
              className={`processing-job processing-job--${job.status}`}
            >
              <div className="processing-job-main">
                <div>
                  <span
                    className={`badge processing-status processing-status--${job.status}`}
                  >
                    {statusLabels[job.status] ?? job.status}
                  </span>
                  <strong>
                    {JOB_LABELS[job.job_type] ||
                      job.job_type.replaceAll("_", " ")}
                  </strong>
                  {job.book_id && (
                    <a href={`/books/${job.book_id}`}>
                      {job.book_title || `Book ${job.book_id}`}
                    </a>
                  )}
                </div>
                <small>
                  #{job.id} · {formatDate(job.created_at)}
                  {job.request_id && ` · Request ${job.request_id}`}
                </small>
              </div>
              <p>{job.progress_detail || "Waiting"}</p>
              <JobProgress job={job} runningState={runningState} />
              {job.error && (
                <pre className="processing-job-error">{job.error}</pre>
              )}
              <div className="processing-job-actions">
                {activeStatuses.has(job.status) && (
                  <button
                    className="btn-text"
                    onClick={() => cancelMutation.mutate(job.id)}
                    disabled={cancelMutation.isPending || job.cancel_requested}
                  >
                    {job.cancel_requested ? "Cancellation requested" : "Cancel"}
                  </button>
                )}
                {retryableStatuses.has(job.status) && (
                  <button
                    onClick={() => retryMutation.mutate(job.id)}
                    disabled={retryMutation.isPending}
                  >
                    Retry
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

export default ProcessingJobs;
