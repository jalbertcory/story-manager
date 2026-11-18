import type { Schemas } from "../api/client";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  alignImportedAudiobook,
  bulkImportedAudiobookAction,
  getAudiobookOverview,
  rebuildImportedAudiobook,
  retryImportedAudiobook,
} from "../api/audiobook";
import {
  ACTIVE_AUDIO_STATES,
  audioActionHref,
  audioStateClass,
  isEditionJobAction,
} from "../lib/audioState";
import type { EditionJobAction } from "../lib/audioState";
import { queryKeys } from "../lib/queryKeys";
import { retryProcessingJob } from "../api/processing";
import { useLocation } from "../lib/router";
import AudiobookToolsPanel from "./AudiobookToolsPanel";
import ConfirmActionDialog from "./ConfirmActionDialog";

type OverviewBook = Schemas["AudiobookOverviewBook"];
type OverviewSource = Schemas["AudiobookOverviewSource"];
type BulkSkip = Schemas["AudiobookBulkActionSkip"];

const ATTENTION_FILTER = "attention";
const ALL_FILTER = "all";
// The bulk endpoint takes at most this many editions per request.
const BULK_BATCH_SIZE = 500;

const KIND_LABELS: Record<OverviewBook["audio_kind"], string> = {
  human: "Human narration",
  tts: "AI narration",
  both: "Human and AI narration",
};

async function queueEditionAction(
  action: EditionJobAction,
  editionId: number,
  jobId: number | null,
) {
  if (action === "retry_processing") {
    if (jobId == null)
      throw new Error("The failed processing job is unavailable.");
    return retryProcessingJob(jobId);
  }
  if (action === "retry_import") return retryImportedAudiobook(editionId);
  if (action === "rebuild") return rebuildImportedAudiobook(editionId);
  return alignImportedAudiobook(editionId);
}

type BulkPlan = {
  action: EditionJobAction;
  label: string;
  editionIds: number[];
  bookIds: Set<number>;
};

// A state filter can be acted on in one go when every human edition shown in
// it has the same queueable next action.
function bulkPlanFor(books: OverviewBook[], filter: string): BulkPlan | null {
  if (filter === ALL_FILTER || filter === ATTENTION_FILTER) return null;
  let plan: BulkPlan | null = null;
  for (const book of books) {
    for (const source of book.sources) {
      const next = source.next_action;
      if (
        source.state !== filter ||
        source.edition_id == null ||
        !next ||
        !isEditionJobAction(next)
      ) {
        continue;
      }
      if (plan && plan.action !== next) return null;
      plan ??= {
        action: next,
        label: source.next_action_label ?? next,
        editionIds: [],
        bookIds: new Set(),
      };
      plan.editionIds.push(source.edition_id);
      plan.bookIds.add(book.book_id);
    }
  }
  return plan && plan.editionIds.length > 1 ? plan : null;
}

async function runBulkPlan(plan: BulkPlan) {
  const queued: number[] = [];
  const skipped: BulkSkip[] = [];
  for (
    let start = 0;
    start < plan.editionIds.length;
    start += BULK_BATCH_SIZE
  ) {
    try {
      const result = await bulkImportedAudiobookAction({
        action: plan.action,
        edition_ids: plan.editionIds.slice(start, start + BULK_BATCH_SIZE),
      });
      queued.push(...result.queued);
      skipped.push(...result.skipped);
    } catch (error) {
      if (start === 0) throw error;
      // Earlier batches were already queued; say so rather than only failing.
      const message = error instanceof Error ? error.message : String(error);
      const remaining = plan.editionIds.length - start;
      throw new Error(
        `${describeBulkResult(plan.label, queued.length, skipped)} Stopped before the last ${plural(remaining, "audiobook")}: ${message}`,
        { cause: error },
      );
    }
  }
  return { queued, skipped };
}

function plural(count: number, noun: string) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function describeBulkResult(
  label: string,
  queued: number,
  skipped: BulkSkip[],
) {
  const parts = [
    queued > 0
      ? `${label} queued for ${plural(queued, "audiobook")}.`
      : "Nothing was queued.",
  ];
  if (skipped.length > 0) {
    const reasons = new Map<string, number>();
    for (const { reason } of skipped) {
      reasons.set(reason, (reasons.get(reason) ?? 0) + 1);
    }
    const summary = [...reasons]
      .map(([reason, count]) => (count > 1 ? `${reason} (${count})` : reason))
      .join("; ");
    parts.push(`Skipped ${skipped.length}: ${summary}.`);
  }
  return parts.join(" ");
}

function matchesFilter(book: OverviewBook, filter: string) {
  if (filter === ALL_FILTER) return true;
  if (filter === ATTENTION_FILTER) return book.needs_attention;
  return book.sources.some((source) => source.state === filter);
}

function SourceProgress({ source }: { source: OverviewSource }) {
  if (!ACTIVE_AUDIO_STATES.has(source.state) || source.progress_total <= 0) {
    return null;
  }
  return (
    <progress
      aria-label={`${source.name} progress`}
      value={source.progress_current}
      max={source.progress_total}
    />
  );
}

function AudiobookOverview() {
  const queryClient = useQueryClient();
  const { search } = useLocation();
  const [filter, setFilter] = useState(
    () => new URLSearchParams(search).get("state") || ALL_FILTER,
  );
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("");
  // The plan the confirmation dialog shows, kept fixed while it is open so a
  // refetch cannot change which audiobooks "Queue all" sends.
  const [pendingBulk, setPendingBulk] = useState<BulkPlan | null>(null);

  const overview = useQuery({
    queryKey: queryKeys.audiobookOverview,
    queryFn: ({ signal }) => getAudiobookOverview({ signal }),
    // Follow running imports, alignment and narration closely; otherwise a
    // slow refresh catches work started elsewhere.
    refetchInterval: ({ state }) =>
      state.data?.books.some((book) =>
        book.sources.some((source) => ACTIVE_AUDIO_STATES.has(source.state)),
      )
        ? 10_000
        : 60_000,
  });

  const action = useMutation({
    mutationFn: ({
      next,
      source,
    }: {
      book: OverviewBook;
      next: EditionJobAction;
      source: OverviewSource & { edition_id: number };
    }) => queueEditionAction(next, source.edition_id, source.processing_job_id),
    onSuccess: (_edition, { book, source }) => {
      setNotice(`${source.next_action_label} queued for ${book.title}.`);
      refreshAfterQueueing();
      void queryClient.invalidateQueries({
        queryKey: queryKeys.audiobook.imports(book.book_id),
      });
    },
  });

  const bulk = useMutation({
    mutationFn: runBulkPlan,
    onSuccess: ({ queued, skipped }, plan) => {
      setPendingBulk(null);
      setNotice(describeBulkResult(plan.label, queued.length, skipped));
    },
    // A failed later batch may still have queued the earlier ones.
    onSettled: (_result, _error, plan) => {
      refreshAfterQueueing();
      for (const bookId of plan.bookIds) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.audiobook.imports(bookId),
        });
      }
    },
  });

  function refreshAfterQueueing() {
    for (const queryKey of [
      queryKeys.audiobookOverview,
      queryKeys.attentionDashboard,
      queryKeys.humanAudiobookRebuildPreview,
      queryKeys.processingJobs.all,
      queryKeys.activeProcessingJobs,
    ]) {
      void queryClient.invalidateQueries({ queryKey });
    }
  }

  const data = overview.data;
  const needle = query.trim().toLocaleLowerCase();
  const books = useMemo(
    () =>
      (data?.books ?? []).filter(
        (book) =>
          matchesFilter(book, filter) &&
          (!needle ||
            book.title.toLocaleLowerCase().includes(needle) ||
            book.author.toLocaleLowerCase().includes(needle)),
      ),
    [data, filter, needle],
  );
  const bulkPlan = useMemo(() => bulkPlanFor(books, filter), [books, filter]);

  const chips = [
    { key: ALL_FILTER, label: "All", count: data?.total_count ?? 0 },
    {
      key: ATTENTION_FILTER,
      label: "Needs attention",
      count: data?.attention_count ?? 0,
    },
    ...(data?.counts ?? []).map(({ state, label, count }) => ({
      key: state,
      label,
      count,
    })),
  ];

  const renderAction = (book: OverviewBook, source: OverviewSource) => {
    const next = source.next_action;
    if (!next || !source.next_action_label) return null;
    const href = audioActionHref(next, book.book_id);
    if (href) {
      return (
        <a className="audio-overview-link" href={href}>
          {source.next_action_label}
        </a>
      );
    }
    const editionId = source.edition_id;
    if (!isEditionJobAction(next) || editionId == null) return null;
    const busy =
      action.isPending && action.variables.source.edition_id === editionId;
    return (
      <button
        type="button"
        className="btn-sm"
        disabled={busy}
        aria-label={`${source.next_action_label}: ${book.title}, ${source.name}`}
        onClick={() => {
          setNotice("");
          action.mutate({
            book,
            next,
            source: { ...source, edition_id: editionId },
          });
        }}
      >
        {busy ? "Queueing…" : source.next_action_label}
      </button>
    );
  };

  return (
    <div className="attention-page audio-overview">
      <header className="attention-page-header">
        <div>
          <h2>Audiobooks</h2>
          <p>
            Every human-narrated and AI audiobook, its current state, and what
            to do next.
          </p>
        </div>
        <button
          className="btn-text"
          onClick={() => {
            void overview.refetch();
          }}
          disabled={overview.isFetching}
        >
          {overview.isFetching ? "Checking…" : "Refresh"}
        </button>
      </header>

      {overview.isLoading && <p>Checking audiobooks…</p>}
      {overview.error && (
        <p className="error" role="alert">
          {overview.error.message}
        </p>
      )}

      {data && (
        <>
          {!data.transcription_configured && (
            <p className="hint">
              No transcription provider is set up, so human audiobooks use
              estimated sentence timing.{" "}
              <a href="/settings/audio-ai">Set up transcription</a>
            </p>
          )}
          <div
            className="audio-overview-filters"
            role="group"
            aria-label="Filter audiobooks by state"
          >
            {chips.map((chip) => (
              <button
                key={chip.key}
                type="button"
                className="audio-overview-chip"
                aria-pressed={filter === chip.key}
                onClick={() => setFilter(chip.key)}
              >
                {chip.label} <span>{chip.count}</span>
              </button>
            ))}
          </div>
          <label className="audio-overview-search">
            Find audiobooks
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Title or author"
            />
          </label>
          {bulkPlan && (
            <div className="audio-overview-bulk">
              <button
                type="button"
                disabled={bulk.isPending}
                onClick={() => {
                  setNotice("");
                  bulk.reset();
                  setPendingBulk(bulkPlan);
                }}
              >
                {bulkPlan.label} for all {bulkPlan.editionIds.length}
              </button>
            </div>
          )}
          {notice && (
            <p className="job-queued-notice" role="status">
              {notice} <a href="/activity/processing">View processing</a>
            </p>
          )}
          {action.isError && (
            <p className="error" role="alert">
              {action.error.message}
            </p>
          )}
          {bulk.isError && !pendingBulk && (
            <p className="error" role="alert">
              {bulk.error.message}
            </p>
          )}

          {data.total_count === 0 ? (
            <p className="empty-state">
              No audiobooks yet.{" "}
              <a href="/import?type=audiobook">Import an audiobook</a> or enable
              AI narration on a book.
            </p>
          ) : books.length === 0 ? (
            <p className="empty-state">No audiobooks match this filter.</p>
          ) : (
            <ul className="audio-overview-list" aria-label="Audiobooks">
              {books.map((book) => (
                <li key={book.book_id} className="audio-overview-book">
                  <div className="audio-overview-title">
                    <a href={`/books/${book.book_id}/audiobooks?tab=sources`}>
                      {book.title}
                    </a>
                    <span>
                      {book.author || "Unknown author"} ·{" "}
                      {KIND_LABELS[book.audio_kind]}
                    </span>
                  </div>
                  <ul className="audio-overview-sources">
                    {book.sources.map((source) => (
                      <li
                        key={`${source.kind}-${source.edition_id ?? "tts"}`}
                        className="audio-overview-source"
                      >
                        <div className="audio-overview-source-main">
                          <span className="audio-overview-source-name">
                            {source.name}
                          </span>
                          <span className={audioStateClass(source.state)}>
                            {source.state_label}
                          </span>
                          {renderAction(book, source)}
                        </div>
                        <SourceProgress source={source} />
                        {source.state_detail && (
                          <small>{source.state_detail}</small>
                        )}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <section
        className="audio-overview-maintenance"
        aria-labelledby="audio-overview-maintenance"
      >
        <h2 id="audio-overview-maintenance">Maintenance</h2>
        <AudiobookToolsPanel />
      </section>

      {pendingBulk && (
        <ConfirmActionDialog
          open
          title={`${pendingBulk.label} for ${plural(pendingBulk.editionIds.length, "audiobook")}?`}
          confirmLabel="Queue all"
          busyLabel="Queueing…"
          isPending={bulk.isPending}
          onCancel={() => setPendingBulk(null)}
          onConfirm={() => bulk.mutate(pendingBulk)}
        >
          <p>
            This queues one job for each audiobook shown. An audiobook whose
            state changed since this page loaded is skipped.
          </p>
          {bulk.isError && (
            <p className="error" role="alert">
              {bulk.error.message}
            </p>
          )}
        </ConfirmActionDialog>
      )}
    </div>
  );
}

export default AudiobookOverview;
