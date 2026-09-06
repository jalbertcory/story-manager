import type { Schemas } from "../../api/client";
import { errorMessage } from "../../lib/errors";
export type ActionKind = "job" | "refresh" | "cover";
export type ActionItem =
  | Schemas["AttentionJobItem"]
  | Schemas["AttentionBookItem"]
  | Schemas["AttentionFileItem"];
type Job = Schemas["ProcessingJob"];
interface ActionRequest {
  title: string;
  pending?: boolean;
  job?: Job;
  error?: string;
}
import { useEffect, useRef, useState } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { getProcessingJob } from "../../api/processing";
import { queueProcessingJobs, retryProcessingJob } from "../../api/processing";

const keyFor = (kind: ActionKind, item: ActionItem) =>
  `${kind}:${"id" in item ? item.id : item.book_id}`;
const active = (status?: string) =>
  ["queued", "running"].includes(status || "");

export default function useAttentionActions(onRefresh?: () => unknown) {
  const client = useQueryClient();
  const [requests, setRequests] = useState<Record<string, ActionRequest>>({});
  const locks = useRef(new Set<string>());
  const completed = useRef(new Set<string>());
  const tracked = Object.entries(requests).filter(
    (entry): entry is [string, ActionRequest & { job: Job }] =>
      Boolean(entry[1].job),
  );
  const queries = useQueries({
    queries: tracked.map(([, result]) => ({
      queryKey: ["attention-action-job", result.job.id],
      queryFn: () => getProcessingJob(result.job.id),
      initialData: result.job,
      refetchInterval: ({ state }: { state: { data: Job | undefined } }) =>
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
      void client.invalidateQueries({ queryKey: [key] });
  };
  const statuses = tracked.map(([key], index) => ({
    key,
    job: queries[index]?.data,
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
  const busy = (kind: ActionKind, item: ActionItem) => {
    const result = results.find((r) => r.key === keyFor(kind, item));
    return Boolean(
      result?.pending || (result?.job && active(result.job.status)),
    );
  };
  const run = async (kind: ActionKind, item: ActionItem) => {
    const key = keyFor(kind, item);
    if (locks.current.has(key) || busy(kind, item)) return;
    locks.current.add(key);
    completed.current.delete(key);
    const title =
      ("title" in item ? item.title : item.book_title) || "Library task";
    setRequests((previous) => ({
      ...previous,
      [key]: { title, pending: true },
    }));
    try {
      const job =
        "id" in item
          ? await retryProcessingJob(item.id)
          : (
              await queueProcessingJobs({
                job_type: kind === "cover" ? "retry_cover" : "refresh_book",
                book_ids: [item.book_id],
                payload: {},
              })
            ).jobs[0];
      if (!job)
        throw new Error("The server did not queue a job. Please retry.");
      client.setQueryData(["attention-action-job", job.id], job);
      setRequests((previous) => ({ ...previous, [key]: { title, job } }));
      invalidate();
    } catch (error) {
      setRequests((previous) => ({
        ...previous,
        [key]: { title, error: errorMessage(error) },
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
    runMany: async (kind: ActionKind, items: ActionItem[]) => {
      for (const item of items) await run(kind, item);
    },
  };
}
