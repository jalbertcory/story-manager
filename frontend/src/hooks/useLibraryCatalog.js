import { useInfiniteQuery } from "@tanstack/react-query";

import { getBookCatalog } from "../api/books";

function useLibraryCatalog({
  q,
  view,
  review,
  audiobook,
  genre,
  sortBy,
  sortOrder,
  enabled = true,
  series,
  universe,
  source,
}) {
  return useInfiniteQuery({
    queryKey: [
      "book-catalog",
      {
        q,
        view,
        review,
        audiobook,
        genre,
        sortBy,
        sortOrder,
        series,
        universe,
        source,
      },
    ],
    queryFn: ({ pageParam }) =>
      getBookCatalog({
        q,
        series,
        universe,
        source,
        view,
        review,
        audiobook,
        genre,
        sortBy,
        sortOrder,
        cursor: pageParam,
      }),
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
