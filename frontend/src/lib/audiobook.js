export function chapterLabel(chapter) {
  const title = chapter?.title?.trim();
  return title || `Chapter ${chapter?.chapter_number ?? ""}`.trim();
}
