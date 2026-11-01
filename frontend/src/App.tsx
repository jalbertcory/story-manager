import { errorMessage } from "./lib/errors";
import type { MouseEvent } from "react";
import type { NavigationState, OpenBook } from "./types";
import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import "./App.css";
import "./Workspace.css";
import { getAuthStatus, logout } from "./api/auth";
import { getBook } from "./api/books";
import useActiveProcessingJobs from "./hooks/useActiveProcessingJobs";
import { getAttentionDashboard } from "./api/dashboard";
import AdminLogin from "./components/AdminLogin";
import ErrorBoundary from "./components/ErrorBoundary";
import NotFound from "./components/NotFound";
import BookOverview from "./components/BookOverview";
import LibraryWorkspace from "./components/LibraryWorkspace";
import AttentionDashboard from "./components/AttentionDashboard";
import Icon, { type IconName } from "./components/ui/Icon";
import ThemeToggle from "./components/ui/ThemeToggle";

// The library, book overview, and attention views load with the app; other
// pages are fetched on first visit to keep the initial bundle small.
const BookSettings = lazy(() => import("./components/BookSettings"));
const WebUpdates = lazy(() => import("./components/WebUpdates"));
const SettingsHome = lazy(() => import("./components/SettingsHome"));
const AddBook = lazy(() => import("./components/AddBook"));
const AudiobookSettings = lazy(() => import("./components/AudiobookSettings"));
const CleaningConfigs = lazy(() => import("./components/CleaningConfigs"));
const SchedulerStatus = lazy(() => import("./components/SchedulerStatus"));
const Logs = lazy(() => import("./components/Logs"));
const Utilities = lazy(() => import("./components/Utilities"));
const ProcessingJobs = lazy(() => import("./components/ProcessingJobs"));
import {
  buildBookPath,
  getPrimarySection,
  parseLocation,
  parseNavigationState,
  PRIMARY_NAV,
  SECTION_NAV,
} from "./lib/navigation";
import { allowNavigation } from "./lib/navigationGuard";
import { onUnauthorized } from "./lib/authSession";
import { queryKeys } from "./lib/queryKeys";
import { RouterContext } from "./lib/router";

const NAV_ICONS: Record<string, IconName> = {
  library: "library",
  updates: "updates",
  review: "review",
  activity: "activity",
  settings: "settings",
};

function currentLocation() {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
    hash: window.location.hash,
  };
}

function currentHref() {
  const { pathname, search, hash } = window.location;
  return `${pathname}${search}${hash}`;
}

type AuthStatus = Awaited<ReturnType<typeof getAuthStatus>>;

export default function App() {
  const queryClient = useQueryClient();
  const [location, setLocation] = useState(currentLocation);
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [authError, setAuthError] = useState("");
  const [sessionExpired, setSessionExpired] = useState(false);
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
  const returnTo = useRef(
    parseNavigationState(window.history.state).returnTo || "/",
  );
  const route = parseLocation(
    location.pathname,
    location.hash,
    location.search,
  );
  const isBook = route.view === "book";
  const notFound = route.view === "not-found";
  const activeTab = route.tab || "library";
  // A 401 from any request means the admin session expired. With app auth
  // disabled (e.g. behind an auth proxy) a 401 is not ours to answer, so the
  // UI is never blocked on a sign-in page.
  const sessionLost = sessionExpired && authStatus?.mode !== "disabled";
  const authenticated = Boolean(authStatus?.authenticated) && !sessionLost;

  const loadAuthStatus = useCallback(() => {
    setAuthError("");
    getAuthStatus()
      .then(setAuthStatus)
      .catch((error: unknown) => setAuthError(errorMessage(error)));
  }, []);
  useEffect(loadAuthStatus, [loadAuthStatus]);
  useEffect(() => onUnauthorized(() => setSessionExpired(true)), []);
  const signedIn = (status: AuthStatus) => {
    setSessionExpired(false);
    setAuthStatus(status);
    // Requests that failed while signed out should run again now.
    void queryClient.invalidateQueries();
  };

  // The location the app is showing and its history state, so a refused Back or
  // Forward can put the address bar back.
  const committed = useRef({
    href: currentHref(),
    state: window.history.state as unknown,
  });
  const commitLocation = useCallback(() => {
    committed.current = {
      href: currentHref(),
      state: window.history.state as unknown,
    };
    setLocation(currentLocation());
  }, []);
  const navigate = useCallback(
    (href: string, state: NavigationState = {}) => {
      if (!allowNavigation(href)) return;
      window.history.replaceState(
        {
          ...parseNavigationState(window.history.state),
          scrollY: window.scrollY,
        },
        "",
      );
      window.history.pushState(
        { ...state, returnTo: state.returnTo || returnTo.current },
        "",
        href,
      );
      pendingScroll.current = state.scrollY ?? null;
      commitLocation();
      window.scrollTo(0, state.scrollY || 0);
    },
    [commitLocation],
  );
  const router = useMemo(() => ({ location, navigate }), [location, navigate]);
  useEffect(() => {
    const onPop = () => {
      // The browser has already moved. If a page with unsaved work refuses to
      // be left, push the page that is still on screen back onto history.
      if (!allowNavigation(currentHref())) {
        window.history.pushState(
          committed.current.state,
          "",
          committed.current.href,
        );
        return;
      }
      pendingScroll.current =
        parseNavigationState(window.history.state).scrollY ?? null;
      returnTo.current =
        parseNavigationState(window.history.state).returnTo || "/";
      commitLocation();
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [commitLocation]);
  useEffect(() => {
    const parsed = parseLocation(
      location.pathname,
      location.hash,
      location.search,
    );
    if (parsed.redirectPath) {
      window.history.replaceState(
        window.history.state,
        "",
        `${parsed.redirectPath}${location.search}${location.hash}`,
      );
      committed.current = {
        href: currentHref(),
        state: window.history.state as unknown,
      };
    }
  }, [location]);

  const bookQuery = useQuery({
    queryKey: queryKeys.books.detail(route.bookId),
    queryFn: ({ signal }) => {
      if (route.bookId == null) throw new Error("No book selected");
      return getBook(route.bookId, { signal });
    },
    enabled: authenticated && isBook,
    refetchInterval: ({ state }) =>
      ["queued", "processing"].includes(state.data?.refresh_status || "")
        ? 2000
        : false,
  });
  const { data: jobs = [] } = useActiveProcessingJobs(authenticated);
  const attention = useQuery({
    queryKey: queryKeys.attentionDashboard,
    queryFn: ({ signal }) => getAttentionDashboard(5, { signal }),
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
      {
        libraryScrollY:
          parseNavigationState(window.history.state).libraryScrollY ?? 0,
      },
    );
  };
  const backToLibrary = () =>
    navigate(returnTo.current, {
      scrollY: parseNavigationState(window.history.state).libraryScrollY || 0,
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
      <div className="app-loading">
        <h1>Story Manager</h1>
        {authError ? (
          <p role="alert">
            {authError}{" "}
            <button type="button" onClick={loadAuthStatus}>
              Try again
            </button>
          </p>
        ) : (
          <p role="status">Loading…</p>
        )}
      </div>
    );
  if (!authenticated)
    return (
      <AdminLogin
        onAuthenticated={signedIn}
        notice={
          sessionLost && authStatus.authenticated
            ? "Your session expired. Sign in again to continue."
            : undefined
        }
      />
    );

  const renderContent = () => {
    if (notFound) return <NotFound />;
    if (isBook) {
      if (bookQuery.isLoading) return <p role="status">Loading book…</p>;
      // A failed background refetch keeps the last good data on screen; only a
      // missing book or a failed first load replaces the page.
      if (!bookQuery.data) {
        if (bookQuery.error)
          return (
            <p role="alert">
              This book could not be loaded: {bookQuery.error.message}{" "}
              <button type="button" onClick={() => void bookQuery.refetch()}>
                Try again
              </button>{" "}
              <a href="/">Return to library</a>
            </p>
          );
        return (
          <p role="alert">
            This book no longer exists. <a href="/">Return to library</a>
          </p>
        );
      }
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
        return <ProcessingJobs key={location.search} />;
      case "scheduler":
        return <SchedulerStatus />;
      case "configs":
        return <CleaningConfigs />;
      case "audio-settings":
        return <AudiobookSettings />;
      case "utilities":
        return <Utilities />;
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
  const activePrimary = isBook
    ? "library"
    : notFound
      ? ""
      : getPrimarySection(activeTab);
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
      <aside className="app-sidebar">
        <a href="/" className="wordmark">
          <span className="wordmark-mark" aria-hidden="true">
            <Icon name="library" size={18} />
          </span>
          <h1>Story Manager</h1>
        </a>
        <nav className="workspace-nav" aria-label="Primary navigation">
          {PRIMARY_NAV.map((item, index) => (
            <a
              key={item.key}
              className={`workspace-nav-link${index === 3 ? " workspace-nav-secondary" : ""}`}
              href={item.path}
              aria-current={activePrimary === item.key ? "page" : undefined}
            >
              <Icon name={NAV_ICONS[item.key] ?? "library"} />
              <span className="nav-label">{item.label}</span>
              <span className="nav-label-short" aria-hidden="true">
                {item.shortLabel}
              </span>
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
        <div className="app-sidebar-footer">
          <ThemeToggle />
          {authStatus.mode === "password" && (
            <button
              className="btn-text sidebar-signout"
              onClick={() => {
                setAuthError("");
                void logout()
                  .then((status) => {
                    setSessionExpired(false);
                    setAuthStatus(status);
                  })
                  .catch((error: unknown) => setAuthError(errorMessage(error)));
              }}
            >
              <Icon name="logout" size={16} />
              <span className="sidebar-signout-label">Sign out</span>
            </button>
          )}
        </div>
      </aside>
      <main className="workspace-main">
        <div className="workspace-content">
          {authError && (
            <p className="error workspace-alert" role="alert">
              {authError}
            </p>
          )}
          {activePrimary === "settings" && activeTab !== "settings" && (
            <a className="settings-back" href="/settings">
              ← Settings
            </a>
          )}
          {secondary.length > 0 && (
            <nav className="segmented-nav" aria-label="Activity view">
              {secondary.map((item) => (
                <a
                  key={item.key}
                  href={item.path}
                  aria-current={activeTab === item.key ? "page" : undefined}
                >
                  {item.label}
                </a>
              ))}
            </nav>
          )}
          <ErrorBoundary
            resetKey={`${location.pathname}${location.search}${location.hash}`}
          >
            <RouterContext.Provider value={router}>
              <Suspense fallback={<p role="status">Loading…</p>}>
                {renderContent()}
              </Suspense>
            </RouterContext.Provider>
          </ErrorBoundary>
        </div>
      </main>
    </div>
  );
}
