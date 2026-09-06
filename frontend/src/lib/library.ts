import type { Book, LibraryValues } from "../types";
import type { components } from "../api/schema";
export function libraryPath(values: LibraryValues) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value != null) params.set(key, String(value));
  return `/${params.size ? `?${params}` : ""}`;
}

export function checkResult(
  book: Pick<Book, "refresh_status">,
  check?: components["schemas"]["WebCheck"] | null,
) {
  if (book.refresh_status === "queued" || book.refresh_status === "processing")
    return {
      tone: "progress",
      label:
        book.refresh_status === "queued" ? "Check queued" : "Checking source…",
      state: "running",
    };
  if (book.refresh_status === "error" || check?.entry_type === "error")
    return { tone: "error", label: "Source check failed", state: "error" };
  if (!check)
    return {
      tone: "muted",
      label: "No source check recorded",
      state: "unknown",
    };
  const delta =
    check.previous_chapter_count != null && check.new_chapter_count != null
      ? check.new_chapter_count - check.previous_chapter_count
      : null;
  const date = check.timestamp
    ? new Date(check.timestamp).toLocaleString()
    : "Date unavailable";
  if (check.entry_type === "updated")
    return {
      tone: "success",
      label: `${delta != null && delta > 0 ? `${delta} chapter${delta === 1 ? "" : "s"} added` : "Content updated"} · ${date}`,
      state: "updated",
    };
  return {
    tone: "muted",
    label: `${check.entry_type === "added" ? "Imported" : "Checked · no changes"} · ${date}`,
    state: "checked",
  };
}
