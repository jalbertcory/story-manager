import { useQuery } from "@tanstack/react-query";

import { getBookCatalog } from "../api/books";

function useLibraryCatalog({ q, sortBy, sortOrder }) {
  return useQuery({
    queryKey: ["book-catalog", { q, sortBy, sortOrder }],
    queryFn: () => getBookCatalog({ q, sortBy, sortOrder }),
    refetchInterval: ({ state }) => {
      const books = state.data ?? [];
      return books.some((book) => book.download_status === "pending") ? 2000 : false;
    },
  });
}

export default useLibraryCatalog;
