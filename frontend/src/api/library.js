import { getJson, sendJson } from "./client";

export function getLibraryGroups({ groupBy, q = "", universe, source }) {
  const params = new URLSearchParams({ group_by: groupBy, q });
  if (universe != null) params.set("universe", universe);
  if (source) params.set("source", source);
  return getJson(
    `/api/library/groups?${params}`,
    "Could not load library groups",
  );
}
export const getUniverses = () => getJson("/api/library/universes");
export const getLibraryBookInfo = (id) =>
  getJson(`/api/library/books/${id}/info`);
export const setUniverseMembership = (body) =>
  sendJson("/api/library/universe-membership", { method: "PUT", body });
