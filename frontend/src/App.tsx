import type { MouseEvent } from "react";
import type { NavigationState, OpenBook } from "./types";
import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import "./App.css";
import "./Workspace.css";
import { getAuthStatus, logout } from "./api/auth";
import { getBook } from "./api/books";
import { getProcessingJobs } from "./api/processing";
import { getAttentionDashboard } from "./api/dashboard";
import AdminLogin from "./components/AdminLogin";
import BookSettings from "./components/BookSettings";
import BookOverview from "./components/BookOverview";
import LibraryWorkspace from "./components/LibraryWorkspace";
import WebUpdates from "./components/WebUpdates";
import SettingsHome from "./components/SettingsHome";
import AddBook from "./components/AddBook";
import AudiobookSettings from "./components/AudiobookSettings";
import CleaningConfigs from "./components/CleaningConfigs";
import SchedulerStatus from "./components/SchedulerStatus";
import Logs from "./components/Logs";
import Utilities from "./components/Utilities";
import ProcessingJobs from "./components/ProcessingJobs";
import AttentionDashboard from "./components/AttentionDashboard";
import {
  buildBookPath,
  getPrimarySection,
  parseLocation,
  PRIMARY_NAV,
  SECTION_NAV,
} from "./lib/navigation";

function currentLocation() {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
    hash: window.location.hash,
  };
}

export default function App() {
  const [location, setLocation] = useState(currentLocation);
  const [authStatus, setAuthStatus] = useState<Awaited<
    ReturnType<typeof getAuthStatus>
  > | null>(null);
  const [authError, setAuthError] = useState("");
  const [pendingImportEntries, setPendingImportEntries] = useState<
    FileSystemEntry[]
  >([]);
  const [libraryFiltersOpen, setLibraryFiltersOpen] = useState(false);
  const [audioTabs, setAudioTabs] = useState<Record<number, string>>({});
  const [globalDragging, setGlobalDragging] = useState(false);
  const pendingScroll = useRef<number | null>(null);
  const restoreLibraryScroll = useCallback(() => {
    if (pendingScroll.current != null) {
      window.scrollTo(0, pendingScroll.current);
      pendingScroll.current = null;
    }
  }, []);
  const returnTo = useRef(window.history.state?.returnTo || "/");
  const route = parseLocation(
    location.pathname,
    location.hash,
    location.search,
  );
  const isBook = route.view === "book";
  const activeTab = route.tab || "library";
  const authenticated = Boolean(authStatus?.authenticated);

  useEffect(() => {
    getAuthStatus()
      .then(setAuthStatus)
      .catch((error) => setAuthError(error.message));
  }, []);
  const navigate = useCallback((href: string, state: NavigationState = {}) => {
    window.history.replaceState(
      { ...window.history.state, scrollY: window.scrollY },
      "",
    );
    window.history.pushState(
      { ...state, returnTo: state.returnTo || returnTo.current },
      "",
      href,
    );
    pendingScroll.current = state.scrollY ?? null;
    setLocation(currentLocation());
    window.scrollTo(0, state.scrollY || 0);
  }, []);
  useEffect(() => {
    const onPop = () => {
      pendingScroll.current = window.history.state?.scrollY ?? null;
      returnTo.current = window.history.state?.returnTo || "/";
      setLocation(currentLocation());
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  useEffect(() => {
    const parsed = parseLocation(
      location.pathname,
      location.hash,
      location.search,
    );
    if (parsed.redirectPath)
      window.history.replaceState(
        window.history.state,
        "",
        `${parsed.redirectPath}${location.search}${location.hash}`,
      );
  }, [location]);

  const bookQuery = useQuery({
    queryKey: ["book", route.bookId],
    queryFn: () => {
      if (route.bookId == null) throw new Error("No book selected");
      return getBook(route.bookId);
    },
    enabled: authenticated && isBook,
    refetchInterval: ({ state }) =>
      ["queued", "processing"].includes(state.data?.refresh_status || "")
        ? 2000
        : false,
  });
  const { data: jobs = [] } = useQuery({
    queryKey: ["active-processing-jobs"],
    queryFn: () =>
      getProcessingJobs({ statuses: "queued,running", limit: 100 }),
    enabled: authenticated,
    refetchInterval: 5000,
  });
  const attention = useQuery({
    queryKey: ["attention-dashboard"],
    queryFn: () => getAttentionDashboard(5),
    enabled: authenticated && activeTab === "attention",
    staleTime: 30000,
    refetchInterval: jobs.length ? 5000 : 60000,
  });
  useEffect(() => {
    if (route.bookId != null && route.bookSection === "audiobooks") {
      const bookId = route.bookId;
      const tab = route.audiobookTab || "sources";
      setAudioTabs((tabs) =>
        tabs[bookId] === tab ? tabs : { ...tabs, [bookId]: tab },
      );
    }
  }, [isBook, route.bookId, route.bookSection, route.audiobookTab]);
  const onEntriesConsumed = useCallback(() => setPendingImportEntries([]), []);
  const openBook: OpenBook = (book, libraryReturn) => {
    returnTo.current =
      libraryReturn || `${location.pathname}${location.search}${location.hash}`;
    navigate(buildBookPath(book.id, "overview"), {
      returnTo: returnTo.current,
      libraryScrollY: window.scrollY,
    });
  };
  const bookSection = (section: string, tab?: string) => {
    if (route.bookId == null) return;
    navigate(
      buildBookPath(
        route.bookId,
        section,
        tab || audioTabs[route.bookId] || "sources",
      ),
      { libraryScrollY: window.history.state?.libraryScrollY },
    );
  };
  const backToLibrary = () =>
    navigate(returnTo.current, {
      scrollY: window.history.state?.libraryScrollY || 0,
    });

  useEffect(() => {
    const onDragOver = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes("Files")) {
        e.preventDefault();
        setGlobalDragging(true);
      }
    };
    const onDragLeave = (e: DragEvent) => {
      if (!e.relatedTarget) setGlobalDragging(false);
    };
    const onDrop = (e: DragEvent) => {
      if (!e.dataTransfer?.types.includes("Files")) return;
      e.preventDefault();
      setGlobalDragging(false);
      const entries = Array.from(e.dataTransfer.items)
        .map((item) => item.webkitGetAsEntry?.())
        .filter((entry): entry is FileSystemEntry => entry != null);
      if (
        entries.some(
          (entry) => entry.isDirectory || /\.(epub|zip)$/i.test(entry.name),
        )
      ) {
        setPendingImportEntries(entries);
        navigate("/import?type=books");
      }
    };
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [navigate]);

  if (!authStatus)
    return (
      <div className="app-container">
        <h1>Story Manager</h1>
        <p role={authError ? "alert" : "status"}>{authError || "Loading…"}</p>
      </div>
    );
  if (!authenticated) return <AdminLogin onAuthenticated={setAuthStatus} />;

  const renderContent = () => {
    if (isBook) {
      if (bookQuery.isLoading) return <p role="status">Loading book…</p>;
      if (bookQuery.error || !bookQuery.data)
        return (
          <p role="alert">
            This book could not be loaded. <a href="/">Return to library</a>
          </p>
        );
      const book = bookQuery.data;
      if (route.bookSection === "overview")
        return (
          <BookOverview
            key={book.id}
            book={book}
            onBack={backToLibrary}
            backLabel={
              returnTo.current.startsWith("/updates")
                ? "Back to web updates"
                : "Back to library"
            }
            onSection={bookSection}
          />
        );
      return (
        <BookSettings
          key={book.id}
          book={book}
          onBack={backToLibrary}
          bookSection={route.bookSection}
          audiobookTab={route.audiobookTab}
          onNavigationChange={bookSection}
        />
      );
    }
    switch (activeTab) {
      case "updates":
        return <WebUpdates onEdit={openBook} />;
      case "review":
        return <Utilities key="review" section="metadata" reviewOnly />;
      case "settings":
        return <SettingsHome />;
      case "attention":
        return (
          <AttentionDashboard
            data={attention.data}
            isLoading={attention.isLoading}
            error={attention.error}
            onRefresh={attention.refetch}
            isRefreshing={attention.isFetching}
          />
        );
      case "processing":
        return <ProcessingJobs />;
      case "scheduler":
        return <SchedulerStatus />;
      case "configs":
        return <CleaningConfigs />;
      case "audio-settings":
        return <AudiobookSettings />;
      case "utilities":
        return <Utilities key={location.search} />;
      case "logs":
        return <Logs />;
      case "import":
        return (
          <AddBook
            initialEntries={pendingImportEntries}
            onEntriesConsumed={onEntriesConsumed}
          />
        );
      default:
        return (
          <LibraryWorkspace
            filtersOpen={libraryFiltersOpen}
            onFiltersToggle={setLibraryFiltersOpen}
            key={`${location.search}${location.hash}`}
            search={location.search}
            hash={location.hash}
            onReady={restoreLibraryScroll}
            onNavigate={navigate}
            onEdit={openBook}
          />
        );
    }
  };
  const activePrimary = isBook ? "library" : getPrimarySection(activeTab);
  const secondary =
    !isBook && activePrimary === "activity" ? SECTION_NAV.activity : [];
  const followInternalLink = (event: MouseEvent<HTMLDivElement>) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    const link =
      event.target instanceof Element ? event.target.closest("a") : null;
    if (!link || link.target || link.hasAttribute("download")) return;
    const url = new URL(link.href);
    if (
      url.origin !== window.location.origin ||
      url.pathname.startsWith("/api/") ||
      url.pathname.startsWith("/reader")
    )
      return;
    event.preventDefault();
    if (/^\/books\/\d+/.test(url.pathname) && !isBook)
      returnTo.current = `${location.pathname}${location.search}${location.hash}`;
    navigate(`${url.pathname}${url.search}${url.hash}`);
  };
  return (
    <div
      className={`app-container workspace-shell${globalDragging ? " drag-over" : ""}`}
      onClick={followInternalLink}
    >
      <header className="app-header">
        <a href="/" className="wordmark">
          <h1>Story Manager</h1>
        </a>
        {authStatus.mode === "password" && (
          <button
            className="btn-text"
            onClick={async () => setAuthStatus(await logout())}
          >
            Sign out
          </button>
        )}
      </header>
      <div className="workspace-layout">
        <nav className="workspace-nav" aria-label="Primary navigation">
          {PRIMARY_NAV.map((item, index) => (
            <a
              key={item.key}
              className={`workspace-nav-link${index === 3 ? " workspace-nav-secondary" : ""}`}
              href={item.path}
              aria-current={activePrimary === item.key ? "page" : undefined}
            >
              {item.label}
              {item.key === "activity" && jobs.length > 0 && (
                <span
                  className="workspace-count"
                  aria-label={`${jobs.length} active jobs`}
                >
                  {jobs.length}
                </span>
              )}
            </a>
          ))}
        </nav>
        <main className="workspace-main">
          {activePrimary === "settings" && activeTab !== "settings" && (
            <a className="settings-back" href="/settings">
              ← Settings
            </a>
          )}
          {secondary.length > 0 && (
            <div className="workspace-subnav">
              <label>
                Activity view
                <select
                  aria-label="Activity view"
                  value={activeTab}
                  onChange={(e) =>
                    navigate(
                      secondary.find((item) => item.key === e.target.value)
                        ?.path || "/activity",
                    )
                  }
                >
                  {secondary.map((item) => (
                    <option key={item.key} value={item.key}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
          {renderContent()}
        </main>
      </div>
    </div>
  );
}
