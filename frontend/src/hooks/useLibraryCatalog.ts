import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { getBookCatalog } from "../api/books";
import useActiveProcessingJobs from "./useActiveProcessingJobs";
import { queryKeys } from "../lib/queryKeys";

type CatalogEntry = Awaited<ReturnType<typeof getBookCatalog>>["items"][number];

const isInFlight = (book: CatalogEntry) =>
  book.download_status === "pending" ||
  book.refresh_status === "queued" ||
  book.refresh_status === "processing";

function useLibraryCatalog({
  enabled = true,
  ...params
}: Parameters<typeof getBookCatalog>[0] & { enabled?: boolean }) {
  const queryClient = useQueryClient();
  const catalog = useInfiniteQuery({
    queryKey: queryKeys.bookCatalog.list(params),
    queryFn: ({ pageParam, signal }) =>
      getBookCatalog({ ...params, cursor: pageParam }, { signal }),
    initialPageParam: "",
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled,
    // Refetching re-reads every loaded page, so only poll slowly as a fallback
    // for work that is not a processing job; finished jobs refresh it below.
    refetchInterval: ({ state }) =>
      state.data?.pages.some((page) => page.items.some(isInFlight))
        ? 15_000
        : false,
  });

  // Refresh the catalog when a processing job it was waiting on finishes.
  const jobs = useActiveProcessingJobs(enabled).data;
  const previousJobIds = useRef<Set<number> | null>(null);
  useEffect(() => {
    if (!jobs) return;
    const ids = new Set(jobs.map((job) => job.id));
    const finished = [...(previousJobIds.current ?? [])].some(
      (id) => !ids.has(id),
    );
    previousJobIds.current = ids;
    if (finished)
      void queryClient.invalidateQueries({
        queryKey: queryKeys.bookCatalog.all,
      });
  }, [jobs, queryClient]);

  return catalog;
}

export default useLibraryCatalog;
