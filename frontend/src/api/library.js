import { getJson, sendJson } from "./client";

export function getLibraryGroups({
  groupBy,
  q = "",
  universe,
  source,
  genre,
  audiobook,
  review,
  sortBy = "title",
  sortOrder = "asc",
  cursor = "",
  limit = 30,
}) {
  const params = new URLSearchParams({
    group_by: groupBy,
    q,
    sort_by: sortBy,
    sort_order: sortOrder,
    limit,
  });
  if (universe != null) params.set("universe", universe);
  for (const [key, value] of Object.entries({
    source,
    genre,
    audiobook,
    review,
    cursor,
  }))
    if (value) params.set(key, value);
  return getJson(
    `/api/library/groups?${params}`,
    "Could not load library groups",
  ).then((data) =>
    Array.isArray(data)
      ? { items: data, next_cursor: null, total_count: data.length, facets: {} }
      : data,
  );
}
export const getUniverses = () => getJson("/api/library/universes");
export const getLibraryBookInfo = (id) =>
  getJson(`/api/library/books/${id}/info`);
export const setUniverseMembership = (body) =>
  sendJson("/api/library/universe-membership", { method: "PUT", body });
