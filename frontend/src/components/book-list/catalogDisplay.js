import { getApiCoverUrl } from "../../api/covers";

export function getCoverUrl(book) {
  if (!book.cover_path) {
    return null;
  }
  return getApiCoverUrl(book.id);
}

export function getSeriesGenreTags(books) {
  if (!books.length) return [];
  return books[0].effective_series_genre_tags || [];
}
