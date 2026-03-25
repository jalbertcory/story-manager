import { useCallback, useEffect, useState } from "react";
import "./App.css";
import { getBook } from "./api/books";
import BookList from "./components/BookList";
import BookSettings from "./components/BookSettings";
import AddBook from "./components/AddBook.jsx";
import CleaningConfigs from "./components/CleaningConfigs.jsx";
import SchedulerStatus from "./components/SchedulerStatus.jsx";
import Logs from "./components/Logs.jsx";
import Utilities from "./components/Utilities.jsx";
import useDebouncedValue from "./hooks/useDebouncedValue";
import useLibraryCatalog from "./hooks/useLibraryCatalog";
import { buildBookPath, buildTabPath, parseLocation, TABS } from "./lib/navigation";

function App() {
  const [q, setQ] = useState("");
  const [sortBy, setSortBy] = useState("title");
  const [sortOrder, setSortOrder] = useState("asc");
  const [editingBook, setEditingBook] = useState(null);
  const [activeTab, setActiveTab] = useState("library");
  const [libraryView, setLibraryView] = useState("series");
  const [addBookOpen, setAddBookOpen] = useState(false);
  const debouncedQuery = useDebouncedValue(q.trim(), 300);

  const applyLocation = useCallback(async (pathname, hash, stateData = null) => {
    const parsed = parseLocation(pathname, hash);
    if (parsed.view === "book") {
      if (stateData?.id === parsed.bookId) {
        setEditingBook(stateData);
        return;
      }

      const book = await getBook(parsed.bookId);
      if (book) {
        setEditingBook(book);
        return;
      }

      window.history.replaceState({ view: "tab", tab: "library" }, "", buildTabPath("library", "series"));
      setEditingBook(null);
      setActiveTab("library");
      setLibraryView("series");
      return;
    }

    setEditingBook(null);
    setActiveTab(parsed.tab);
    setLibraryView(parsed.libraryView);
  }, []);

  const navigate = (view, data = null) => {
    if (view === "book" && data?.id) {
      window.history.pushState({ view, data }, "", buildBookPath(data.id));
      setEditingBook(data);
    } else {
      const nextPath = buildTabPath(view, libraryView);
      const tab = TABS.find((item) => item.key === view) || TABS[0];
      window.history.pushState({ view: "tab", tab: tab.key }, "", nextPath);
      setEditingBook(null);
      setActiveTab(tab.key);
    }
  };

  const handleLibraryViewChange = (view) => {
    setLibraryView(view);
    window.history.pushState({ view: "tab", tab: "library" }, "", buildTabPath("library", view));
  };

  useEffect(() => {
    void applyLocation(window.location.pathname, window.location.hash);
  }, [applyLocation]);

  useEffect(() => {
    const onPop = (e) => {
      void applyLocation(window.location.pathname, window.location.hash, e.state?.data ?? null);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [applyLocation]);

  const {
    data: catalog = [],
    isLoading,
    error,
  } = useLibraryCatalog({
    q: debouncedQuery,
    sortBy,
    sortOrder,
  });

  const handleClearSearch = () => {
    setQ("");
  };

  const handleSortByChange = (newSortBy) => {
    setSortBy(newSortBy);
    setSortOrder("asc");
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

  if (editingBook) {
    return (
      <BookSettings book={editingBook} onBack={() => window.history.back()} />
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
              />
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
