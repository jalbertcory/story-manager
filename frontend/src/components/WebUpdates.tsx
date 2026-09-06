import { checkResult } from "../lib/library";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAllBookCatalog, refreshBook } from "../api/books";
import { getWebChecks } from "../api/library";
import { getSchedulerJob, triggerScheduler } from "../api/scheduler";
import type { OpenBook } from "../types";
import { BookRow } from "./book-list/BookCards";
import SchedulerStatus from "./SchedulerStatus";

export default function WebUpdates({ onEdit }: { onEdit: OpenBook }) {
  const client = useQueryClient();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [notice, setNotice] = useState("");
  const booksQuery = useQuery({
    queryKey: ["web-update-books"],
    queryFn: () => getAllBookCatalog({ view: "web" }),
    refetchInterval: 5000,
  });
  const checksQuery = useQuery({
    queryKey: ["web-checks"],
    queryFn: getWebChecks,
    refetchInterval: 5000,
  });
  const schedule = useQuery({
    queryKey: ["web-update-schedule"],
    queryFn: getSchedulerJob,
    refetchInterval: 10000,
  });
  const refresh = useMutation({
    mutationFn: async (id: number | null) =>
      id ? refreshBook(id) : triggerScheduler(),
    onSuccess: (_, id) => {
      setNotice(
        id ? "Source check queued." : "Check queued for all followed novels.",
      );
      for (const key of [
        "web-update-books",
        "active-processing-jobs",
        "web-checks",
      ])
        void client.invalidateQueries({ queryKey: [key] });
    },
  });
  const checks = new Map(
    (checksQuery.data || []).map((check) => [check.book_id, check]),
  );
  const books = (booksQuery.data || []).map((book) => ({
    book,
    result: checkResult(book, checks.get(book.id)),
  }));
  const failed = books.filter(({ result }) => result.state === "error").length;
  const rows = books.filter(
    ({ book, result }) =>
      `${book.title} ${book.author}`.toLowerCase().includes(q.toLowerCase()) &&
      (filter === "all" || result.state === filter),
  );
  rows.sort(
    (a, b) =>
      Number(b.result.state === "error") - Number(a.result.state === "error") ||
      a.book.title.localeCompare(b.book.title),
  );
  return (
    <section>
      <div className="workspace-heading">
        <div>
          <h2>Web updates</h2>
          <p className="hint">{books.length} followed novels</p>
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
              {failed} {failed === 1 ? "novel needs" : "novels need"} attention
            </strong>
            <p>
              Review the affected sources. Your other books are listed below.
            </p>
          </div>
          <button onClick={() => setFilter("error")}>Review errors</button>
        </div>
      )}
      <div className="library-toolbar">
        <input
          aria-label="Search web novels"
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
            <option value="all">All novels</option>
            <option value="updated">Content updated</option>
            <option value="error">Needs attention</option>
            <option value="running">Checking</option>
            <option value="checked">Checked / imported</option>
          </select>
        </label>
      </div>
      {notice && <p role="status">{notice}</p>}
      {[booksQuery.error, checksQuery.error, schedule.error, refresh.error]
        .filter(Boolean)
        .map((error, i) => (
          <p className="error" role="alert" key={i}>
            {error?.message}
          </p>
        ))}
      {(booksQuery.isLoading || checksQuery.isLoading) && (
        <p role="status">Loading source checks…</p>
      )}
      {rows.map(({ book, result }) => (
        <BookRow
          key={book.id}
          book={book}
          onEdit={onEdit}
          status={result}
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
          No novels match this view.{" "}
          <a href="/import?type=web">Add a web novel</a>
        </p>
      )}
      {schedule.data?.next_run_at && (
        <p className="hint">
          Next automatic check:{" "}
          {new Date(schedule.data.next_run_at).toLocaleString()} ·{" "}
          {schedule.data.schedule_timezone ||
            Intl.DateTimeFormat().resolvedOptions().timeZone}
        </p>
      )}
      <details className="workspace-disclosure">
        <summary>Schedule and previous runs</summary>
        <SchedulerStatus />
      </details>
    </section>
  );
}
