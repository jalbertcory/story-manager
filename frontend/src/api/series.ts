import { api, unwrap } from "./client";

export function getSeries() {
  return unwrap(api.GET("/api/series"), "Failed to load series");
}

export function renameSeries(series: string, newName: string) {
  return unwrap(
    api.PUT("/api/series/{series_name}", {
      params: { path: { series_name: series } },
      body: { new_name: newName },
    }),
    "Failed to rename series",
  );
}

export function mergeSeries(source: string, target: string) {
  return unwrap(
    api.POST("/api/series/merge", { body: { source, target } }),
    "Failed to merge series",
  );
}

export function reorderSeries(series: string, orderedBookIds: number[]) {
  return unwrap(
    api.POST("/api/series/{series_name}/reorder", {
      params: { path: { series_name: series } },
      body: { ordered_book_ids: orderedBookIds },
    }),
    "Failed to reorder series",
  );
}

export function updateSeriesGenres(series: string, userGenreTags: string[]) {
  return unwrap(
    api.PUT("/api/series/{series_name}/genres", {
      params: { path: { series_name: series } },
      body: { user_genre_tags: userGenreTags },
    }),
    "Failed to update series genres",
  );
}
