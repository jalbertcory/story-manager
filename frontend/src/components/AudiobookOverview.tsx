import type { Schemas } from "../api/client";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  alignImportedAudiobook,
  getAudiobookOverview,
  rebuildImportedAudiobook,
  retryImportedAudiobook,
} from "../api/audiobook";
import {
  ACTIVE_AUDIO_STATES,
  audioActionHref,
  audioStateClass,
  EDITION_JOB_ACTIONS,
} from "../lib/audioState";
import type { AudioNextAction } from "../lib/audioState";
import { queryKeys } from "../lib/queryKeys";
import { useLocation } from "../lib/router";

type OverviewBook = Schemas["AudiobookOverviewBook"];
type OverviewSource = Schemas["AudiobookOverviewSource"];

const ATTENTION_FILTER = "attention";
const ALL_FILTER = "all";

const KIND_LABELS: Record<OverviewBook["audio_kind"], string> = {
  human: "Human narration",
  tts: "AI narration",
  both: "Human and AI narration",
};

function queueEditionAction(action: AudioNextAction, editionId: number) {
  if (action === "retry_import") return retryImportedAudiobook(editionId);
  if (action === "rebuild") return rebuildImportedAudiobook(editionId);
  return alignImportedAudiobook(editionId);
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
      source,
    }: {
      book: OverviewBook;
      source: OverviewSource & { edition_id: number };
    }) =>
      queueEditionAction(
        source.next_action as AudioNextAction,
        source.edition_id,
      ),
    onSuccess: (_edition, { book, source }) => {
      setNotice(`${source.next_action_label} queued for ${book.title}.`);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.audiobookOverview,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.attentionDashboard,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.audiobook.imports(book.book_id),
      });
    },
  });

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
    if (!EDITION_JOB_ACTIONS.has(next) || editionId == null) return null;
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
          action.mutate({ book, source: { ...source, edition_id: editionId } });
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
    </div>
  );
}

export default AudiobookOverview;
