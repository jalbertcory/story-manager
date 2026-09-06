export function chapterLabel(
  chapter:
    | { title?: string | null; chapter_number?: number | null }
    | null
    | undefined,
) {
  const title = chapter?.title?.trim();
  return title || `Chapter ${chapter?.chapter_number ?? ""}`.trim();
}
