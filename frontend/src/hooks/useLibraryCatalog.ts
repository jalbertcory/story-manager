import { useInfiniteQuery } from "@tanstack/react-query";

import { getBookCatalog } from "../api/books";

function useLibraryCatalog({
  enabled = true,
  ...params
}: Parameters<typeof getBookCatalog>[0] & { enabled?: boolean }) {
  return useInfiniteQuery({
    queryKey: ["book-catalog", params],
    queryFn: ({ pageParam }) => getBookCatalog({ ...params, cursor: pageParam }),
    initialPageParam: "",
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled,
    refetchInterval: ({ state }) => {
      const books = state.data?.pages.flatMap((page) => page.items) ?? [];
      const hasInFlight = books.some(
        (book) =>
          book.download_status === "pending" ||
          book.refresh_status === "queued" ||
          book.refresh_status === "processing",
      );
      return hasInFlight ? 2000 : false;
    },
  });
}

export default useLibraryCatalog;
