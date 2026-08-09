import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import "./App.css";
import { getAuthStatus, logout } from "./api/auth";
import { getBook } from "./api/books";
import AdminLogin from "./components/AdminLogin.jsx";
import BookList from "./components/BookList";
import BookSettings from "./components/BookSettings";
import AddBook from "./components/AddBook.jsx";
import AudiobookSettings from "./components/AudiobookSettings.jsx";
import CleaningConfigs from "./components/CleaningConfigs.jsx";
import SchedulerStatus from "./components/SchedulerStatus.jsx";
import Logs from "./components/Logs.jsx";
import Utilities from "./components/Utilities.jsx";
import ProcessingJobs from "./components/ProcessingJobs.jsx";
import { getProcessingJobs } from "./api/processing";
import { getAttentionDashboard } from "./api/dashboard";
import AttentionDashboard from "./components/AttentionDashboard.jsx";
import useDebouncedValue from "./hooks/useDebouncedValue";
import useLibraryCatalog from "./hooks/useLibraryCatalog";
import {
  buildBookPath,
  buildTabPath,
  getPrimarySection,
  getRoute,
  parseLocation,
  PRIMARY_NAV,
  SECTION_NAV,
} from "./lib/navigation";

function App() {
  const [q, setQ] = useState("");
  const [sortBy, setSortBy] = useState("title");
  const [sortOrder, setSortOrder] = useState("asc");
  const [editingBook, setEditingBook] = useState(null);
  const [bookSection, setBookSection] = useState("details");
  const [audiobookTab, setAudiobookTab] = useState("sources");
  const [activeTab, setActiveTab] = useState("library");
  const [libraryView, setLibraryView] = useState("series");
  const [pendingImportEntries, setPendingImportEntries] = useState([]);
  const [globalDragging, setGlobalDragging] = useState(false);
  const [authStatus, setAuthStatus] = useState(null);
  const debouncedQuery = useDebouncedValue(q.trim(), 300);

  useEffect(() => {
    let mounted = true;
    getAuthStatus().then((status) => {
      if (mounted) {
        setAuthStatus(status);
      }
    });
    return () => {
      mounted = false;
    };
  }, []);

  const applyLocation = useCallback(
    async (pathname, hash, search, stateData = null) => {
      const parsed = parseLocation(pathname, hash, search);
      if (parsed.view === "book") {
        if (parsed.legacyBookPath) {
          window.history.replaceState(
            window.history.state,
            "",
            buildBookPath(parsed.bookId, "details"),
          );
        }
        setBookSection(parsed.bookSection);
        setAudiobookTab(parsed.audiobookTab);
        if (stateData?.id === parsed.bookId) {
          setEditingBook(stateData);
          return;
        }

        const book = await getBook(parsed.bookId);
        if (book) {
          setEditingBook(book);
          return;
        }

        window.history.replaceState(
          { view: "tab", tab: "library" },
          "",
          buildTabPath("library", "series"),
        );
        setEditingBook(null);
        setActiveTab("library");
        setLibraryView("series");
        return;
      }

      if (parsed.redirectPath) {
        window.history.replaceState(
          window.history.state,
          "",
          `${parsed.redirectPath}${search}${hash || ""}`,
        );
      }
      setEditingBook(null);
      setActiveTab(parsed.tab);
      setLibraryView(parsed.libraryView);
    },
    [],
  );

  const navigate = (view, data = null) => {
    if (view === "book" && data?.id) {
      window.history.pushState(
        { view, data },
        "",
        buildBookPath(data.id, "details"),
      );
      setEditingBook(data);
      setBookSection("details");
      setAudiobookTab("sources");
    } else {
      const nextPath = buildTabPath(view, libraryView);
      const route = getRoute(view);
      window.history.pushState(
        { view: "tab", tab: route.key },
        "",
        nextPath,
      );
      setEditingBook(null);
      setActiveTab(route.key);
    }
  };

  const handleLibraryViewChange = (view) => {
    setLibraryView(view);
    window.history.pushState(
      { view: "tab", tab: "library" },
      "",
      buildTabPath("library", view),
    );
  };

  useEffect(() => {
    if (!authStatus?.authenticated) {
      return;
    }
    void applyLocation(
      window.location.pathname,
      window.location.hash,
      window.location.search,
    );
  }, [applyLocation, authStatus?.authenticated]);

  useEffect(() => {
    if (!authStatus?.authenticated) {
      return undefined;
    }
    const onPop = (e) => {
      void applyLocation(
        window.location.pathname,
        window.location.hash,
        window.location.search,
        e.state?.data ?? null,
      );
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [applyLocation, authStatus?.authenticated]);

  const {
    data: catalog = [],
    isLoading,
    error,
  } = useLibraryCatalog({
    q: debouncedQuery,
    sortBy,
    sortOrder,
    enabled: Boolean(authStatus?.authenticated),
  });

  const { data: activeProcessingJobs = [] } = useQuery({
    queryKey: ["active-processing-jobs"],
    queryFn: () => getProcessingJobs({ statuses: "queued,running", limit: 100 }),
    enabled: Boolean(authStatus?.authenticated),
    refetchInterval: 3000,
  });

  const attentionQuery = useQuery({
    queryKey: ["attention-dashboard"],
    queryFn: () => getAttentionDashboard(5),
    enabled: Boolean(authStatus?.authenticated),
    staleTime: 30_000,
    refetchInterval: activeProcessingJobs.length > 0 ? 5000 : 60_000,
  });

  const handleClearSearch = () => {
    setQ("");
  };

  const handleSortByChange = (newSortBy) => {
    setSortBy(newSortBy);
    setSortOrder(newSortBy === "audiobook_enabled" ? "desc" : "asc");
  };

  const handleToggleSortOrder = () => {
    setSortOrder((current) => (current === "asc" ? "desc" : "asc"));
  };

  const handleEdit = async (book) => {
    const fullBook = await getBook(book.id);
    if (fullBook) {
      navigate("book", fullBook);
    }
  };

  const handleBookNavigation = (nextSection, nextAudiobookTab = audiobookTab) => {
    if (!editingBook) return;
    const nextPath = buildBookPath(
      editingBook.id,
      nextSection,
      nextAudiobookTab,
    );
    const currentPath = `${window.location.pathname}${window.location.search}`;
    if (currentPath !== nextPath) {
      window.history.pushState(
        { view: "book", data: editingBook },
        "",
        nextPath,
      );
    }
    setBookSection(nextSection);
    setAudiobookTab(nextAudiobookTab);
  };

  const handleLogout = async () => {
    const nextStatus = await logout();
    setAuthStatus(nextStatus);
  };

  const handleImportEntriesConsumed = useCallback(() => {
    setPendingImportEntries([]);
  }, []);

  useEffect(() => {
    const onDragOver = (e) => {
      e.preventDefault();
      setGlobalDragging(true);
    };
    const onDragLeave = (e) => {
      // Only clear when the drag exits the browser window entirely
      if (
        e.relatedTarget === null ||
        !document.documentElement.contains(e.relatedTarget)
      ) {
        setGlobalDragging(false);
      }
    };
    const onDrop = (e) => {
      e.preventDefault();
      setGlobalDragging(false);
      const entries = Array.from(e.dataTransfer.items)
        .map((item) => item.webkitGetAsEntry?.())
        .filter(Boolean);
      const hasRelevant = entries.some(
        (entry) =>
          entry.isDirectory ||
          entry.name.toLowerCase().endsWith(".epub") ||
          entry.name.toLowerCase().endsWith(".zip"),
      );
      if (hasRelevant) {
        window.history.pushState(
          { view: "tab", tab: "import" },
          "",
          "/import?type=books",
        );
        setEditingBook(null);
        setActiveTab("import");
        setPendingImportEntries(entries);
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
  }, []);

  if (authStatus === null) {
    return (
      <div className="app-container">
        <header className="app-header">
          <h1>Story Manager</h1>
        </header>
        <p>Loading...</p>
      </div>
    );
  }

  if (!authStatus.authenticated) {
    return <AdminLogin onAuthenticated={setAuthStatus} />;
  }

  const renderTabContent = () => {
    switch (activeTab) {
      case "attention":
        return (
          <AttentionDashboard
            data={attentionQuery.data}
            isLoading={attentionQuery.isLoading}
            error={attentionQuery.error}
            onRefresh={attentionQuery.refetch}
            isRefreshing={attentionQuery.isFetching}
          />
        );
      case "configs":
        return <CleaningConfigs />;
      case "scheduler":
        return <SchedulerStatus />;
      case "processing":
        return <ProcessingJobs />;
      case "logs":
        return <Logs />;
      case "utilities":
        return <Utilities />;
      case "audio-settings":
        return <AudiobookSettings />;
      case "import":
        return (
          <AddBook
            initialEntries={pendingImportEntries}
            onEntriesConsumed={handleImportEntriesConsumed}
          />
        );
      default:
        return (
          <>
            <div className="library-page-heading">
              <h2>Library</h2>
              <button
                type="button"
                className="btn-primary"
                onClick={() => navigate("import")}
              >
                Add to library
              </button>
            </div>
            <div className="search-controls">
              <div className="search-input-wrap">
                <svg
                  className="search-icon"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  width="16"
                  height="16"
                >
                  <path
                    fillRule="evenodd"
                    d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.45 4.38l3.09 3.08a.75.75 0 11-1.06 1.06l-3.09-3.08A7 7 0 012 9z"
                    clipRule="evenodd"
                  />
                </svg>
                <input
                  type="text"
                  placeholder="Search by title, author, series, or tag"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                />
                {q && (
                  <button
                    className="search-clear"
                    onClick={handleClearSearch}
                    aria-label="Clear search"
                  >
                    ×
                  </button>
                )}
              </div>
              <div className="sort-controls">
                <select
                  aria-label="Sort library by"
                  value={sortBy}
                  onChange={(e) => handleSortByChange(e.target.value)}
                >
                  <option value="title">Title</option>
                  <option value="author">Author</option>
                  <option value="word_count">Word Count</option>
                  <option value="updated_at">Last Updated</option>
                  <option value="audiobook_enabled">Audiobook Enabled</option>
                </select>
                <button
                  className="sort-order-btn"
                  onClick={handleToggleSortOrder}
                  aria-label="Toggle sort order"
                >
                  {sortOrder === "asc" ? "↑" : "↓"}
                </button>
              </div>
            </div>
            {isLoading && <p>Loading...</p>}
            {error && <p className="error">{error.message}</p>}
            <BookList
              books={catalog}
              onEdit={handleEdit}
              libraryView={libraryView}
              onLibraryViewChange={handleLibraryViewChange}
              sortBy={sortBy}
              sortOrder={sortOrder}
            />
          </>
        );
    }
  };

  const activePrimary = editingBook
    ? "library"
    : getPrimarySection(activeTab);
  const secondaryItems = editingBook ? [] : SECTION_NAV[activePrimary] || [];

  const renderPrimaryBadge = (sectionKey) => {
    if (sectionKey !== "activity") return null;
    return (
      <span className="nav-status-counts">
        {attentionQuery.data?.total_count > 0 && (
          <span
            className="nav-job-count nav-job-count--attention"
            aria-label={`${attentionQuery.data.total_count} ${attentionQuery.data.total_count === 1 ? "item needs" : "items need"} attention`}
          >
            {attentionQuery.data.total_count}
          </span>
        )}
        {activeProcessingJobs.length > 0 && (
          <span
            className="nav-job-count nav-job-count--active"
            aria-label={`${activeProcessingJobs.length} active processing ${activeProcessingJobs.length === 1 ? "job" : "jobs"}`}
          >
            {activeProcessingJobs.length}
          </span>
        )}
      </span>
    );
  };

  return (
    <div
      className={`app-container${editingBook ? " app-container--book" : ""}${globalDragging ? " drag-over" : ""}`}
    >
      <header className="app-header">
        <h1>Story Manager</h1>
        {authStatus.mode === "password" && (
          <button className="btn-text" onClick={handleLogout}>
            Sign Out
          </button>
        )}
      </header>
      <nav className="main-tabs" aria-label="Primary navigation">
        {PRIMARY_NAV.map((section) => (
          <a
            key={section.key}
            className={`main-tab${activePrimary === section.key ? " main-tab--active" : ""}`}
            href={section.path}
            onClick={(event) => {
              event.preventDefault();
              navigate(section.defaultTab);
            }}
            aria-current={activePrimary === section.key ? "page" : undefined}
          >
            {section.label}
            {renderPrimaryBadge(section.key)}
          </a>
        ))}
      </nav>
      {secondaryItems.length > 0 && (
        <nav
          className="section-navigation"
          aria-label={`${PRIMARY_NAV.find((item) => item.key === activePrimary)?.label} sections`}
        >
          {secondaryItems.map((item) => (
            <a
              key={item.key}
              className={`section-navigation-link${activeTab === item.key ? " section-navigation-link--active" : ""}`}
              href={item.path}
              onClick={(event) => {
                event.preventDefault();
                navigate(item.key);
              }}
              aria-current={activeTab === item.key ? "page" : undefined}
            >
              {item.label}
            </a>
          ))}
        </nav>
      )}
      <main>
        {editingBook ? (
          <BookSettings
            book={editingBook}
            onBack={() => navigate("library")}
            bookSection={bookSection}
            audiobookTab={audiobookTab}
            onNavigationChange={handleBookNavigation}
          />
        ) : (
          renderTabContent()
        )}
      </main>
    </div>
  );
}

export default App;
