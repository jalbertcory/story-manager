export const PRIMARY_NAV = [
  { key: "library", label: "Library", path: "/", defaultTab: "library" },
  {
    key: "updates",
    label: "Web updates",
    path: "/updates",
    defaultTab: "updates",
  },
  {
    key: "review",
    label: "Review suggestions",
    path: "/review",
    defaultTab: "review",
  },
  {
    key: "activity",
    label: "Background activity",
    path: "/activity",
    defaultTab: "attention",
  },
  {
    key: "settings",
    label: "Settings",
    path: "/settings",
    defaultTab: "settings",
  },
];

export const SECTION_NAV = {
  activity: [
    { key: "attention", label: "Overview", path: "/activity" },
    {
      key: "processing",
      label: "Processing jobs",
      path: "/activity/processing",
    },
    {
      key: "scheduler",
      label: "Scheduled runs",
      path: "/activity/scheduled-runs",
    },
  ],
  settings: [
    { key: "configs", label: "Cleaning rules", path: "/settings/cleaning" },
    {
      key: "audio-settings",
      label: "Audio & AI",
      path: "/settings/audio-ai",
    },
    {
      key: "utilities",
      label: "Library tools",
      path: "/settings/library-tools",
    },
    { key: "logs", label: "Logs", path: "/settings/logs" },
  ],
};

const ROUTES = [
  { key: "library", path: "/", section: "library" },
  { key: "import", path: "/import", section: "library" },
  { key: "updates", path: "/updates", section: "updates" },
  { key: "review", path: "/review", section: "review" },
  { key: "settings", path: "/settings", section: "settings" },
  ...SECTION_NAV.activity.map((route) => ({
    ...route,
    section: "activity",
  })),
  ...SECTION_NAV.settings.map((route) => ({
    ...route,
    section: "settings",
  })),
];

const LEGACY_ROUTES = {
  "/attention": "attention",
  "/processing": "processing",
  "/scheduler": "scheduler",
  "/configs": "configs",
  "/audio-settings": "audio-settings",
  "/utilities": "utilities",
  "/logs": "logs",
};

export const LIBRARY_VIEWS = ["series", "standalone", "web"];

export const BOOK_SECTIONS = ["overview", "details", "audiobooks"];

export const AUDIOBOOK_TABS = [
  { key: "sources", label: "Sources" },
  { key: "listen-read", label: "Listen & Read" },
  { key: "progress", label: "Progress" },
  { key: "analysis", label: "Analysis" },
  { key: "characters", label: "Characters" },
  { key: "script-editor", label: "Script Editor" },
  { key: "chapter-assembly", label: "Chapter Assembly" },
];

function normalizePath(pathname) {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

export function getRoute(tabKey) {
  return ROUTES.find((route) => route.key === tabKey) || ROUTES[0];
}

export function getPrimarySection(tabKey) {
  return getRoute(tabKey).section;
}

export function parseLocation(pathname, hash, search = "") {
  const normalizedPath = normalizePath(pathname);
  const match = normalizedPath.match(
    /^\/books\/(\d+)(?:\/(overview|details|audiobooks))?$/,
  );
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

  const legacyTab = LEGACY_ROUTES[normalizedPath];
  const route = legacyTab
    ? getRoute(legacyTab)
    : ROUTES.find((item) => item.path === normalizedPath) || ROUTES[0];
  const libraryView = LIBRARY_VIEWS.includes(hash?.slice(1))
    ? hash.slice(1)
    : "series";
  return {
    view: "tab",
    tab: route.key,
    libraryView,
    ...(legacyTab ? { redirectPath: route.path } : {}),
  };
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
  return `/books/${bookId}/${section}`;
}

export function buildTabPath(tabKey, libraryView = "series") {
  const route = getRoute(tabKey);
  return route.key === "library" ? `${route.path}#${libraryView}` : route.path;
}
