import {
  checkResult,
  isRecentUpdate,
  lastUpdateLabel,
  RECENT_UPDATE_DAYS,
  timeAgo,
} from "../lib/library";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAllBookCatalog, refreshBook } from "../api/books";
import { getWebChecks } from "../api/library";
import {
  getSchedulerHistory,
  getSchedulerJob,
  triggerScheduler,
} from "../api/scheduler";
import { useLocation } from "../lib/router";
import type { OpenBook } from "../types";
import { BookRow } from "./book-list/BookCards";
import { queryKeys } from "../lib/queryKeys";

const FILTERS = [
  ["all", "All stories"],
  ["recent", `New chapters in the last ${RECENT_UPDATE_DAYS} days`],
  ["error", "Failed checks"],
  ["running", "Checking now"],
  ["quiet", "Nothing new lately"],
] as const;

// Other pages link straight to a filtered list with ?show=recent or ?show=error.
function requestedFilter(search: string) {
  const show = new URLSearchParams(search).get("show");
  return FILTERS.some(([value]) => value === show) ? (show as string) : "all";
}

export default function WebUpdates({ onEdit }: { onEdit: OpenBook }) {
  const client = useQueryClient();
  const { search } = useLocation();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState(() => requestedFilter(search));
  useEffect(() => setFilter(requestedFilter(search)), [search]);
  const [notice, setNotice] = useState("");
  const booksQuery = useQuery({
    queryKey: queryKeys.webUpdateBooks,
    queryFn: ({ signal }) => getAllBookCatalog({ view: "web" }, { signal }),
    refetchInterval: 5000,
  });
  const checksQuery = useQuery({
    queryKey: queryKeys.webChecks,
    queryFn: getWebChecks,
    refetchInterval: 5000,
  });
  const schedule = useQuery({
    queryKey: queryKeys.webUpdateSchedule,
    queryFn: getSchedulerJob,
    refetchInterval: 10000,
  });
  const latestRun = useQuery({
    queryKey: queryKeys.schedulerLatestRun,
    queryFn: ({ signal }) => getSchedulerHistory({ limit: 1 }, { signal }),
    refetchInterval: 10000,
  });
  const lastRun = latestRun.data?.[0];
  const refresh = useMutation({
    mutationFn: async (id: number | null) =>
      id ? refreshBook(id) : triggerScheduler(),
    onSuccess: (_, id) => {
      setNotice(
        id ? "Update check queued." : "Update check queued for every story.",
      );
      for (const queryKey of [
        queryKeys.webUpdateBooks,
        queryKeys.activeProcessingJobs,
        queryKeys.webChecks,
      ])
        void client.invalidateQueries({ queryKey });
    },
  });
  const checks = new Map(
    (checksQuery.data || []).map((check) => [check.book_id, check]),
  );
  const books = (booksQuery.data || []).map((book) => {
    const check = checks.get(book.id);
    return {
      book,
      check,
      result: checkResult(book, check),
      recent: isRecentUpdate(check),
    };
  });
  const failed = books.filter(({ result }) => result.state === "error").length;
  const recentCount = books.filter(({ recent }) => recent).length;
  const rows = books.filter(
    ({ book, result, recent }) =>
      `${book.title} ${book.author}`.toLowerCase().includes(q.toLowerCase()) &&
      (filter === "all" ||
        (filter === "recent"
          ? recent
          : filter === "quiet"
            ? !recent && !["error", "running"].includes(result.state)
            : result.state === filter)),
  );
  // Failures first, then the stories that most recently gained chapters.
  rows.sort(
    (a, b) =>
      Number(b.result.state === "error") - Number(a.result.state === "error") ||
      (b.check?.last_update_at || "").localeCompare(
        a.check?.last_update_at || "",
      ) ||
      a.book.title.localeCompare(b.book.title),
  );
  return (
    <section>
      <div className="workspace-heading">
        <div>
          <h2>Web updates</h2>
          <p className="hint">
            {books.length} followed {books.length === 1 ? "story" : "stories"}
            {recentCount > 0 &&
              ` · ${recentCount} with new chapters in the last ${RECENT_UPDATE_DAYS} days`}
          </p>
          {lastRun && (
            <p className="hint">
              {lastRun.status === "running"
                ? `Checking every story now (${lastRun.completed_books} of ${lastRun.total_books})`
                : `Last full check ${timeAgo(lastRun.completed_at || lastRun.started_at)}`}
              {" · "}
              {lastRun.updated_count} updated · {lastRun.unchanged_count}{" "}
              unchanged · {lastRun.failed_count} failed
            </p>
          )}
        </div>
        <button
          className="btn-primary"
          disabled={
            refresh.isPending || schedule.data?.run_in_progress || !books.length
          }
          onClick={() => refresh.mutate(null)}
        >
          Check for updates
        </button>
      </div>
      {failed > 0 && (
        <div className="workspace-notice">
          <div>
            <strong>
              {failed} update {failed === 1 ? "check" : "checks"} failed
            </strong>
            <p>
              Each failed story below says what went wrong. Your other stories
              were checked normally.
            </p>
          </div>
          <button onClick={() => setFilter("error")}>Show failed checks</button>
        </div>
      )}
      <div className="library-toolbar">
        <input
          aria-label="Search followed stories"
          placeholder="Search title or author"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <label>
          Show
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            aria-label="Filter web updates"
          >
            {FILTERS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {notice && <p role="status">{notice}</p>}
      {[
        booksQuery.error,
        checksQuery.error,
        schedule.error,
        latestRun.error,
        refresh.error,
      ]
        .filter(Boolean)
        .map((error, i) => (
          <p className="error" role="alert" key={i}>
            {error?.message}
          </p>
        ))}
      {(booksQuery.isLoading || checksQuery.isLoading) && (
        <p role="status">Loading update checks…</p>
      )}
      {rows.map(({ book, check, result }) => (
        <BookRow
          key={book.id}
          book={book}
          onEdit={onEdit}
          status={result}
          subtitle={
            // The latest check often finds nothing; keep the last real update visible.
            result.state !== "updated" && lastUpdateLabel(check)
              ? `Last update: ${lastUpdateLabel(check)}`
              : null
          }
          actions={
            <button
              disabled={refresh.isPending || result.state === "running"}
              onClick={() => refresh.mutate(book.id)}
            >
              {result.state === "error"
                ? "Retry check"
                : result.state === "running"
                  ? "Checking…"
                  : "Check now"}
            </button>
          }
        />
      ))}
      {!booksQuery.isLoading && !rows.length && (
        <p className="empty-state">
          No stories match this view.{" "}
          <a href="/import?type=web">Add a web novel</a>
        </p>
      )}
      <p className="hint">
        {schedule.data?.next_run_at && (
          <>
            Next automatic check:{" "}
            {new Date(schedule.data.next_run_at).toLocaleString()} ·{" "}
            {schedule.data.schedule_timezone ||
              Intl.DateTimeFormat().resolvedOptions().timeZone}
            {" · "}
          </>
        )}
        <a href="/activity/scheduled-runs">Schedule and previous checks</a>
      </p>
    </section>
  );
}
