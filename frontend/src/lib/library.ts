import type { Book, LibraryValues } from "../types";
import type { components } from "../api/schema";
export function libraryPath(values: LibraryValues) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value != null) params.set(key, String(value));
  return `/${params.size ? `?${params}` : ""}`;
}

type WebCheck = components["schemas"]["WebCheck"];
export type WebUpdateEvent = components["schemas"]["WebUpdateEvent"];

// Stories that gained chapters within this many days count as recently updated.
export const RECENT_UPDATE_DAYS = 7;

export function timeAgo(value: string | null | undefined, now = Date.now()) {
  if (!value) return "never";
  const minutes = Math.floor((now - new Date(value).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 60) return `${days}d ago`;
  return new Date(value).toLocaleDateString();
}

export function chaptersAdded(count: number | null | undefined) {
  return count != null && count > 0
    ? `${count} new chapter${count === 1 ? "" : "s"}`
    : "New content";
}

// The last time a check actually brought in new chapters, which later
// "no changes" checks do not replace.
export function lastUpdateLabel(
  check: WebCheck | null | undefined,
  now = Date.now(),
) {
  if (!check?.last_update_at) return null;
  return `${chaptersAdded(check.last_update_chapters_added)} · ${timeAgo(check.last_update_at, now)}`;
}

export function isRecentUpdate(
  check: WebCheck | null | undefined,
  now = Date.now(),
) {
  return Boolean(
    check?.last_update_at &&
    now - new Date(check.last_update_at).getTime() <
      RECENT_UPDATE_DAYS * 86400000,
  );
}

export function checkResult(
  book: Pick<Book, "refresh_status">,
  check?: WebCheck | null,
) {
  if (book.refresh_status === "queued" || book.refresh_status === "processing")
    return {
      tone: "progress",
      label:
        book.refresh_status === "queued"
          ? "Update check queued"
          : "Checking for updates…",
      state: "running",
    };
  if (book.refresh_status === "error" || check?.entry_type === "error") {
    const reason = check?.entry_type === "error" ? check.detail : null;
    return {
      tone: "error",
      label: `Update check failed${reason ? `: ${reason}` : ""}`,
      state: "error",
    };
  }
  if (!check)
    return {
      tone: "muted",
      label: "Not checked for updates yet",
      state: "unknown",
    };
  const date = timeAgo(check.timestamp);
  if (check.entry_type === "updated") {
    const delta =
      check.previous_chapter_count != null && check.new_chapter_count != null
        ? check.new_chapter_count - check.previous_chapter_count
        : null;
    return {
      tone: "success",
      label: `${chaptersAdded(delta)} · ${date}`,
      state: "updated",
    };
  }
  return {
    tone: "muted",
    label: `${check.entry_type === "added" ? "Imported" : "Checked, nothing new"} · ${date}`,
    state: "checked",
  };
}

export interface UpdateDay {
  // Local midnight of the day the updates arrived.
  date: Date;
  // One entry per story, newest first; several checks in a day are combined.
  stories: WebUpdateEvent[];
  chapters: number;
  words: number;
}

// Groups update events (newest first) into local calendar days.
export function updatesByDay(events: WebUpdateEvent[]): UpdateDay[] {
  const days: UpdateDay[] = [];
  for (const event of events) {
    const date = new Date(event.timestamp);
    date.setHours(0, 0, 0, 0);
    let day = days.at(-1);
    if (!day || day.date.getTime() !== date.getTime()) {
      day = { date, stories: [], chapters: 0, words: 0 };
      days.push(day);
    }
    day.chapters += event.chapters_added;
    day.words += event.words_added;
    const story = day.stories.find((s) => s.book_id === event.book_id);
    if (story) {
      story.chapters_added += event.chapters_added;
      story.words_added += event.words_added;
    } else day.stories.push({ ...event });
  }
  return days;
}

export function dayLabel(date: Date, now = Date.now()) {
  const today = new Date(now);
  today.setHours(0, 0, 0, 0);
  const daysAgo = Math.round((today.getTime() - date.getTime()) / 86400000);
  if (daysAgo === 0) return "Today";
  if (daysAgo === 1) return "Yesterday";
  return date.toLocaleDateString(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
}
