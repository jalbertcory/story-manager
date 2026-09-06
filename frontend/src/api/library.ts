import { api, unwrap } from "./client";
import type { Body, Query } from "./client";
export { getWebChecks } from "./admin";

type GroupQuery = Query<"/api/library/groups">;
export interface LibraryGroupParams {
  groupBy: NonNullable<GroupQuery["group_by"]>;
  q?: string;
  universe?: number | null;
  source?: GroupQuery["source"] | "";
  genre?: string;
  audiobook?: GroupQuery["audiobook"] | "";
  review?: GroupQuery["review"] | "";
  sortBy?: GroupQuery["sort_by"];
  sortOrder?: GroupQuery["sort_order"];
  cursor?: string;
  limit?: number;
}
export async function getLibraryGroups({
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
}: LibraryGroupParams) {
  const data = await unwrap(
    api.GET("/api/library/groups", {
      params: {
        query: {
          group_by: groupBy,
          q,
          ...(universe != null ? { universe } : {}),
          ...(source ? { source } : {}),
          ...(genre ? { genre } : {}),
          ...(audiobook ? { audiobook } : {}),
          ...(review ? { review } : {}),
          sort_by: sortBy,
          sort_order: sortOrder,
          ...(cursor ? { cursor } : {}),
          limit,
        },
      },
    }),
    "Could not load library groups",
  );
  return Array.isArray(data)
    ? {
        items: data,
        next_cursor: null,
        total_count: data.length,
        facets: { series: 0, standalone: 0, web: 0, genres: [] },
      }
    : data;
}
export const getUniverses = () => unwrap(api.GET("/api/library/universes"));
export const getLibraryBookInfo = (id: number) =>
  unwrap(
    api.GET("/api/library/books/{book_id}/info", {
      params: { path: { book_id: id } },
    }),
  );
export const setUniverseMembership = (
  body: Body<"/api/library/universe-membership", "put">,
) => unwrap(api.PUT("/api/library/universe-membership", { body }));
