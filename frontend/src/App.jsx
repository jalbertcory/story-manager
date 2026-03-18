import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import "./App.css";
import BookList from "./components/BookList";
import BookSettings from "./components/BookSettings";
import AddBook from "./components/AddBook.jsx";
import CleaningConfigs from "./components/CleaningConfigs.jsx";
import SchedulerStatus from "./components/SchedulerStatus.jsx";
import Logs from "./components/Logs.jsx";
import Utilities from "./components/Utilities.jsx";

const TABS = [
  { key: "library", label: "Library", path: "/" },
  { key: "configs", label: "Cleaning Configs", path: "/configs" },
  { key: "scheduler", label: "Scheduler", path: "/scheduler" },
  { key: "logs", label: "Logs", path: "/logs" },
  { key: "utilities", label: "Utilities", path: "/utilities" },
];

const LIBRARY_VIEWS = ["series", "standalone", "web"];

function parseLocation(pathname, hash) {
  const m = pathname.match(/^\/books\/(\d+)$/);
  if (m) return { view: "book", bookId: parseInt(m[1]) };
  const tab = TABS.find((t) => t.path === pathname);
  const libraryView = LIBRARY_VIEWS.includes(hash?.slice(1)) ? hash.slice(1) : "series";
  return { view: "tab", tab: tab?.key || "library", libraryView };
}

function App() {
  const [q, setQ] = useState("");
  const [sortBy, setSortBy] = useState("title");
  const [sortOrder, setSortOrder] = useState("asc");
  const [searchParams, setSearchParams] = useState({
    q: "",
    sortBy: "title",
    sortOrder: "asc",
  });
  const [editingBook, setEditingBook] = useState(null);
  const [activeTab, setActiveTab] = useState("library");
  const [libraryView, setLibraryView] = useState("series");
  const [addBookOpen, setAddBookOpen] = useState(false);

  const applyLocation = (pathname, hash, stateData = null) => {
    const parsed = parseLocation(pathname, hash);
    if (parsed.view === "book") {
      if (stateData?.id === parsed.bookId) {
        setEditingBook(stateData);
      } else {
        fetch(`/api/books/${parsed.bookId}`)
          .then((r) => (r.ok ? r.json() : null))
          .then((book) => {
            if (book) setEditingBook(book);
            else { setEditingBook(null); setActiveTab("library"); }
          });
      }
    } else {
      setEditingBook(null);
      setActiveTab(parsed.tab);
      setLibraryView(parsed.libraryView);
    }
  };

  const navigate = (view, data = null) => {
    if (view === "book" && data?.id) {
      history.pushState({ view, data }, "", `/books/${data.id}`);
      setEditingBook(data);
    } else {
      const tab = TABS.find((t) => t.key === view) || TABS[0];
      const hash = tab.key === "library" ? `#${libraryView}` : "";
      history.pushState({ view: "tab", tab: tab.key }, "", tab.path + hash);
      setEditingBook(null);
      setActiveTab(tab.key);
    }
  };

  const handleLibraryViewChange = (view) => {
    setLibraryView(view);
    history.pushState({ view: "tab", tab: "library" }, "", `/#${view}`);
  };

  useEffect(() => {
    applyLocation(window.location.pathname, window.location.hash);
  }, []);

  useEffect(() => {
    const onPop = (e) => applyLocation(window.location.pathname, window.location.hash, e.state?.data ?? null);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const {
    data: catalog = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["book-catalog", searchParams],
    queryFn: async () => {
      const { q: sq, sortBy: sb, sortOrder: so } = searchParams;
      const url = sq
        ? `/api/books/catalog?q=${encodeURIComponent(sq)}&sort_by=${encodeURIComponent(sb)}&sort_order=${encodeURIComponent(so)}`
        : `/api/books/catalog?sort_by=${encodeURIComponent(sb)}&sort_order=${encodeURIComponent(so)}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error("Failed to fetch books");
      return res.json();
    },
    refetchInterval: ({ state }) => {
      const books = state.data ?? [];
      return books.some((b) => b.download_status === "pending") ? 2000 : false;
    },
  });

  const handleSearch = () => {
    setSearchParams({ q: q.trim(), sortBy, sortOrder });
  };

  const handleClearSearch = () => {
    setQ("");
    setSearchParams({ q: "", sortBy, sortOrder });
  };

  const handleSortByChange = (newSortBy) => {
    setSortBy(newSortBy);
    setSortOrder("asc");
    setSearchParams({ q: searchParams.q, sortBy: newSortBy, sortOrder: "asc" });
  };

  const handleToggleSortOrder = () => {
    const newOrder = sortOrder === "asc" ? "desc" : "asc";
    setSortOrder(newOrder);
    setSearchParams({ q: searchParams.q, sortBy, sortOrder: newOrder });
  };

  const handleEdit = async (book) => {
    const response = await fetch(`/api/books/${book.id}`);
    if (!response.ok) return;
    navigate("book", await response.json());
  };

  if (editingBook) {
    return (
      <BookSettings book={editingBook} onBack={() => history.back()} />
    );
  }

  const renderTabContent = () => {
    switch (activeTab) {
      case "configs":
        return <CleaningConfigs />;
      case "scheduler":
        return <SchedulerStatus />;
      case "logs":
        return <Logs />;
      case "utilities":
        return <Utilities />;
      default:
        return (
          <>
            <div className="search-controls">
              <input
                type="text"
                placeholder="Search by title, author, or series"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              />
              <button onClick={handleSearch}>Search</button>
              <button onClick={handleClearSearch}>Clear</button>
              <select
                value={sortBy}
                onChange={(e) => handleSortByChange(e.target.value)}
              >
                <option value="title">Title</option>
                <option value="author">Author</option>
                <option value="word_count">Word Count</option>
                <option value="updated_at">Last Updated</option>
              </select>
              <button onClick={handleToggleSortOrder}>
                {sortOrder === "asc" ? "↑" : "↓"}
              </button>
            </div>
            <details className="add-book-details" open={addBookOpen}>
              <summary
                className="add-book-summary"
                onClick={(e) => {
                  e.preventDefault();
                  setAddBookOpen((o) => !o);
                }}
              >
                Add Books
              </summary>
              <AddBook />
            </details>
            {isLoading && <p>Loading...</p>}
            {error && <p className="error">{error.message}</p>}
            <BookList books={catalog} onEdit={handleEdit} libraryView={libraryView} onLibraryViewChange={handleLibraryViewChange} />
          </>
        );
    }
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>Story Manager</h1>
      </header>
      <nav className="main-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            className={`main-tab${activeTab === tab.key ? " main-tab--active" : ""}`}
            onClick={() => navigate(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      {renderTabContent()}
    </div>
  );
}

export default App;
