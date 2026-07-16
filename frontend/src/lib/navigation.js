export const TABS = [
  { key: "library", label: "Library", path: "/" },
  { key: "configs", label: "Cleaning Configs", path: "/configs" },
  { key: "scheduler", label: "Scheduler", path: "/scheduler" },
  { key: "logs", label: "Logs", path: "/logs" },
  { key: "utilities", label: "Utilities", path: "/utilities" },
  { key: "audio-settings", label: "Audio Settings", path: "/audio-settings" },
];

export const LIBRARY_VIEWS = ["series", "standalone", "web"];

export function parseLocation(pathname, hash) {
  const match = pathname.match(/^\/books\/(\d+)$/);
  if (match) {
    return { view: "book", bookId: Number.parseInt(match[1], 10) };
  }

  const tab = TABS.find((item) => item.path === pathname);
  const libraryView = LIBRARY_VIEWS.includes(hash?.slice(1)) ? hash.slice(1) : "series";
  return { view: "tab", tab: tab?.key || "library", libraryView };
}

export function buildBookPath(bookId) {
  return `/books/${bookId}`;
}

export function buildTabPath(tabKey, libraryView) {
  const tab = TABS.find((item) => item.key === tabKey) || TABS[0];
  return tab.key === "library" ? `${tab.path}#${libraryView}` : tab.path;
}
