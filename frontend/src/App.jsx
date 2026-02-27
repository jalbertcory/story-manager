import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import "./App.css";
import BookList from "./components/BookList";
import BookSettings from "./components/BookSettings";
import AddBook from "./components/AddBook.jsx";
import CleaningConfigs from "./components/CleaningConfigs.jsx";

const fetchBooks = async ({ queryKey }) => {
  const [_key, { q, sortBy, sortOrder }] = queryKey;

  let endpoint;
  if (q) {
    endpoint = `/api/books/search?q=${encodeURIComponent(q)}`;
  } else {
    endpoint = `/api/books?sort_by=${encodeURIComponent(sortBy)}&sort_order=${encodeURIComponent(sortOrder)}`;
  }

  const res = await fetch(endpoint);
  if (!res.ok) {
    throw new Error("Failed to fetch books");
  }
  return res.json();
};

function App() {
  const [q, setQ] = useState("");
  const [sortBy, setSortBy] = useState("title");
  const [sortOrder, setSortOrder] = useState("asc");
  const [searchParams, setSearchParams] = useState({ q: "", sortBy: "title", sortOrder: "asc" });
  const [editingBook, setEditingBook] = useState(null);
  const [showConfigs, setShowConfigs] = useState(false);

  const {
    data: books,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["books", searchParams],
    queryFn: fetchBooks,
    initialData: [],
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

  if (editingBook) {
    return (
      <BookSettings book={editingBook} onBack={() => setEditingBook(null)} />
    );
  }

  if (showConfigs) {
    return (
      <CleaningConfigs onBack={() => setShowConfigs(false)} />
    );
  }

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>Story Manager</h1>
        <button className="btn-text" onClick={() => setShowConfigs(true)}>Cleaning Configs</button>
      </header>
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
        <select value={sortBy} onChange={(e) => handleSortByChange(e.target.value)}>
          <option value="title">Title</option>
          <option value="author">Author</option>
          <option value="word_count">Word Count</option>
          <option value="updated_at">Last Updated</option>
        </select>
        <button onClick={handleToggleSortOrder}>
          {sortOrder === "asc" ? "↑" : "↓"}
        </button>
      </div>
      <AddBook />
      {isLoading && <p>Loading...</p>}
      {error && <p className="error">{error.message}</p>}
      <BookList books={books} onEdit={setEditingBook} />
    </div>
  );
}

export default App;
