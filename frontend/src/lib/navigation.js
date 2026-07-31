export const TABS = [
  { key: "library", label: "Library", path: "/" },
  { key: "configs", label: "Cleaning Configs", path: "/configs" },
  { key: "scheduler", label: "Scheduler", path: "/scheduler" },
  { key: "processing", label: "Processing", path: "/processing" },
  { key: "logs", label: "Logs", path: "/logs" },
  { key: "utilities", label: "Utilities", path: "/utilities" },
  { key: "audio-settings", label: "Audio Settings", path: "/audio-settings" },
];

export const LIBRARY_VIEWS = ["series", "standalone", "web"];

export const BOOK_SECTIONS = ["details", "audiobooks"];

export const AUDIOBOOK_TABS = [
  { key: "sources", label: "Sources" },
  { key: "listen-read", label: "Listen & Read" },
  { key: "progress", label: "Progress" },
  { key: "analysis", label: "Analysis" },
  { key: "characters", label: "Characters" },
  { key: "script-editor", label: "Script Editor" },
  { key: "chapter-assembly", label: "Chapter Assembly" },
];

export function parseLocation(pathname, hash, search = "") {
  const match = pathname.match(/^\/books\/(\d+)(?:\/(details|audiobooks))?\/?$/);
  if (match) {
    const requestedTab = new URLSearchParams(search).get("tab");
    const audiobookTab = AUDIOBOOK_TABS.some((tab) => tab.key === requestedTab)
      ? requestedTab
      : "sources";
    return {
      view: "book",
      bookId: Number.parseInt(match[1], 10),
      bookSection: match[2] || "details",
      audiobookTab,
      ...(!match[2] ? { legacyBookPath: true } : {}),
    };
  }

  const tab = TABS.find((item) => item.path === pathname);
  const libraryView = LIBRARY_VIEWS.includes(hash?.slice(1)) ? hash.slice(1) : "series";
  return { view: "tab", tab: tab?.key || "library", libraryView };
}

export function buildBookPath(
  bookId,
  bookSection = "details",
  audiobookTab = "sources",
) {
  const section = BOOK_SECTIONS.includes(bookSection) ? bookSection : "details";
  if (section === "audiobooks") {
    const tab = AUDIOBOOK_TABS.some((item) => item.key === audiobookTab)
      ? audiobookTab
      : "sources";
    return `/books/${bookId}/audiobooks?tab=${encodeURIComponent(tab)}`;
  }
  return `/books/${bookId}/details`;
}

export function buildTabPath(tabKey, libraryView) {
  const tab = TABS.find((item) => item.key === tabKey) || TABS[0];
  return tab.key === "library" ? `${tab.path}#${libraryView}` : tab.path;
}
