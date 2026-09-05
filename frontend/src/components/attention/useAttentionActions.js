import { useEffect, useRef, useState } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { getJson } from "../../api/client";
import { queueProcessingJobs, retryProcessingJob } from "../../api/processing";

const keyFor = (kind, item) =>
  `${kind}:${kind === "job" ? item.id : item.book_id}`;
const active = (status) => ["queued", "running"].includes(status);

export default function useAttentionActions(onRefresh) {
  const client = useQueryClient();
  const [requests, setRequests] = useState({});
  const locks = useRef(new Set());
  const completed = useRef(new Set());
  const tracked = Object.entries(requests).filter(([, result]) => result.job);
  const queries = useQueries({
    queries: tracked.map(([, result]) => ({
      queryKey: ["attention-action-job", result.job.id],
      queryFn: () => getJson(`/api/processing/jobs/${result.job.id}`),
      initialData: result.job,
      refetchInterval: ({ state }) =>
        active(state.data?.status) ? 2000 : false,
    })),
  });
  const invalidate = () => {
    for (const key of [
      "active-processing-jobs",
      "processing-jobs",
      "book-catalog",
      "library-groups",
      "book",
      "library-book-info",
    ])
      client.invalidateQueries({ queryKey: [key] });
  };
  const statuses = tracked.map(([key], index) => ({
    key,
    job: queries[index].data,
  }));
  useEffect(() => {
    let changed = false;
    for (const { key, job } of statuses) {
      if (job && !active(job.status) && !completed.current.has(key)) {
        completed.current.add(key);
        changed = true;
      }
    }
    if (changed) {
      invalidate();
      onRefresh?.();
    }
  });
  const results = Object.entries(requests).map(([key, result]) => {
    const job = statuses.find((entry) => entry.key === key)?.job;
    return {
      ...result,
      key,
      job,
      error:
        result.error ||
        (job?.status === "error"
          ? job.error || "Task failed. Retry or review its details."
          : null),
      message: result.pending
        ? "Queuing…"
        : job?.status === "completed"
          ? "Task completed. Library health has been refreshed."
          : job?.status === "canceled"
            ? "Task canceled."
            : job?.progress_detail ||
              "Queued. Follow progress in Background activity.",
    };
  });
  const busy = (kind, item) => {
    const result = results.find((r) => r.key === keyFor(kind, item));
    return Boolean(
      result?.pending || (result?.job && active(result.job.status)),
    );
  };
  const run = async (kind, item) => {
    const key = keyFor(kind, item);
    if (locks.current.has(key) || busy(kind, item)) return;
    locks.current.add(key);
    completed.current.delete(key);
    const title = item.title || item.book_title || "Library task";
    setRequests((previous) => ({
      ...previous,
      [key]: { title, pending: true },
    }));
    try {
      const job =
        kind === "job"
          ? await retryProcessingJob(item.id)
          : (
              await queueProcessingJobs(
                kind === "cover" ? "retry_cover" : "refresh_book",
                [item.book_id],
              )
            ).jobs[0];
      client.setQueryData(["attention-action-job", job.id], job);
      setRequests((previous) => ({ ...previous, [key]: { title, job } }));
      invalidate();
    } catch (error) {
      setRequests((previous) => ({
        ...previous,
        [key]: { title, error: error.message },
      }));
    } finally {
      locks.current.delete(key);
    }
  };
  return {
    run,
    busy,
    results,
    pollError: queries.some((query) => query.isError),
    runMany: async (kind, items) => {
      for (const item of items) await run(kind, item);
    },
  };
}
