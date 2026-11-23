import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Schemas } from "../api/client";
import { getStoryRecap, queueStoryRecap } from "../api/recaps";
import { queryKeys } from "../lib/queryKeys";

type Entry = Schemas["StoryRecapEntry"];
type Kind = Entry["kind"];

const HEADINGS: Record<Kind, string> = {
  story_so_far: "The story so far",
  book: "This book",
};

function coverage(entry: Entry) {
  if (entry.kind === "book")
    return "A reminder of what happens in this book, ending included.";
  const titles = entry.covered_books.map((book) => book.title);
  return `Covers ${titles.join(", ")}. Nothing from this book.`;
}

function RecapEntry({
  entry,
  busy,
  canWrite,
  onWrite,
}: {
  entry: Entry;
  busy: boolean;
  canWrite: boolean;
  onWrite: (kind: Kind, force: boolean) => void;
}) {
  const written = entry.recap != null;
  return (
    <div className="story-recap-entry">
      <div className="story-recap-heading">
        <div>
          <h4>{HEADINGS[entry.kind]}</h4>
          <p className="hint">{coverage(entry)}</p>
        </div>
        <button
          disabled={busy || !canWrite}
          onClick={() => onWrite(entry.kind, written)}
          aria-label={`${written ? "Rewrite" : "Write"} recap: ${HEADINGS[entry.kind]}`}
        >
          {written ? "Rewrite" : "Write recap"}
        </button>
      </div>
      {entry.stale && (
        <p className="workspace-notice">
          {entry.kind === "book"
            ? "This book has changed since the recap was written."
            : "The earlier books have changed since this recap was written."}
        </p>
      )}
      {entry.recap
        ?.split(/\n+/)
        .filter((paragraph) => paragraph.trim())
        .map((paragraph, index) => (
          <p className="story-recap-text" key={index}>
            {paragraph}
          </p>
        ))}
      {written && entry.updated_at && (
        <p className="hint">
          Written {new Date(entry.updated_at).toLocaleDateString()}
          {entry.llm_model ? ` by ${entry.llm_model}` : ""}
        </p>
      )}
    </div>
  );
}

/** LLM-written reminders of the story; fetched only once the reader opens them. */
export default function StoryRecap({ bookId }: { bookId: number }) {
  const client = useQueryClient();
  const recap = useQuery({
    queryKey: queryKeys.storyRecap(bookId),
    queryFn: ({ signal }) => getStoryRecap(bookId, { signal }),
    refetchInterval: (query) => (query.state.data?.active_job ? 3000 : false),
  });
  const write = useMutation({
    mutationFn: ({ kind, force }: { kind: Kind; force: boolean }) =>
      queueStoryRecap(bookId, { kind, force }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.storyRecap(bookId) });
      void client.invalidateQueries({
        queryKey: queryKeys.activeProcessingJobs,
      });
    },
  });

  if (recap.isPending) return <p role="status">Loading recaps…</p>;
  if (recap.error)
    return (
      <p role="alert" className="error">
        {recap.error.message}
      </p>
    );
  const data = recap.data;
  const job = data.active_job;
  const busy = Boolean(job) || write.isPending;
  const hasEarlierBooks = data.story_so_far.covered_books.length > 0;
  const error = write.error?.message ?? (job ? null : data.last_error);

  return (
    <div className="story-recap">
      {!data.llm_configured && (
        <p className="workspace-notice">
          Recaps are written by a language model.{" "}
          <a href="/settings/audio-ai">Set one up</a> to write them.
        </p>
      )}
      {job && (
        <p role="status">Writing the recap… {job.progress_detail ?? ""}</p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {hasEarlierBooks && (
        <RecapEntry
          entry={data.story_so_far}
          busy={busy}
          canWrite={data.llm_configured}
          onWrite={(kind, force) => write.mutate({ kind, force })}
        />
      )}
      <RecapEntry
        entry={data.book}
        busy={busy}
        canWrite={data.llm_configured}
        onWrite={(kind, force) => write.mutate({ kind, force })}
      />
    </div>
  );
}
