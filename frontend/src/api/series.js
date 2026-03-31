import { getJson, sendJson } from "./client";

export function getSeries() {
  return getJson("/api/series", "Failed to load series");
}

export function renameSeries(series, newName) {
  return sendJson(`/api/series/${encodeURIComponent(series)}`, {
    method: "PUT",
    body: { new_name: newName },
    fallbackMessage: "Failed to rename series",
  });
}

export function mergeSeries(source, target) {
  return sendJson("/api/series/merge", {
    body: { source, target },
    fallbackMessage: "Failed to merge series",
  });
}

export function reorderSeries(series, orderedBookIds) {
  return sendJson(`/api/series/${encodeURIComponent(series)}/reorder`, {
    body: { ordered_book_ids: orderedBookIds },
    fallbackMessage: "Failed to reorder series",
  });
}

export function updateSeriesGenres(series, userGenreTags) {
  return sendJson(`/api/series/${encodeURIComponent(series)}/genres`, {
    method: "PUT",
    body: { user_genre_tags: userGenreTags },
    fallbackMessage: "Failed to update series genres",
  });
}
