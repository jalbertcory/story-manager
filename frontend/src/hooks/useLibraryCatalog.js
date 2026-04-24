import { useQuery } from "@tanstack/react-query";

import { getBookCatalog } from "../api/books";

function useLibraryCatalog({ q, sortBy, sortOrder, enabled = true }) {
  return useQuery({
    queryKey: ["book-catalog", { q, sortBy, sortOrder }],
    queryFn: () => getBookCatalog({ q, sortBy, sortOrder }),
    enabled,
    refetchInterval: ({ state }) => {
      const books = state.data ?? [];
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
