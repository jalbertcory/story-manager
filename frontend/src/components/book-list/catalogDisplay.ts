import type { CatalogBook } from "../../types";
import { getApiCoverUrl } from "../../api/covers";

export function getCoverUrl(book: Pick<CatalogBook, "id" | "cover_path">) {
  if (!book.cover_path) {
    return null;
  }
  return getApiCoverUrl(book.id);
}

export function getSeriesGenreTags(books: CatalogBook[]) {
  if (!books.length) return [];
  return books[0]?.effective_series_genre_tags || [];
}
