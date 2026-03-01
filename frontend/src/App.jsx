import { useState } from "react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import "./App.css";
import BookList from "./components/BookList";
import BookSettings from "./components/BookSettings";
import AddBook from "./components/AddBook.jsx";
import CleaningConfigs from "./components/CleaningConfigs.jsx";
import SchedulerStatus from "./components/SchedulerStatus.jsx";

const PAGE_SIZE = 20;

function App() {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [sortBy, setSortBy] = useState("title");
  const [sortOrder, setSortOrder] = useState("asc");
  const [searchParams, setSearchParams] = useState({ q: "", sortBy: "title", sortOrder: "asc" });
  const [editingBook, setEditingBook] = useState(null);
  const [showConfigs, setShowConfigs] = useState(false);
  const [showScheduler, setShowScheduler] = useState(false);

  const reprocessMutation = useMutation({
    mutationFn: () =>
      fetch("/api/books/reprocess-all", { method: "POST" }).then((r) => r.json()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["books"] }),
  });

  const {
    data,
    isLoading,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["books", searchParams],
    queryFn: async ({ pageParam = 0 }) => {
      const { q: sq, sortBy: sb, sortOrder: so } = searchParams;
      const url = sq
        ? `/api/books/search?q=${encodeURIComponent(sq)}&skip=${pageParam}&limit=${PAGE_SIZE}`
        : `/api/books?sort_by=${encodeURIComponent(sb)}&sort_order=${encodeURIComponent(so)}&skip=${pageParam}&limit=${PAGE_SIZE}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error("Failed to fetch books");
      return res.json();
    },
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length === PAGE_SIZE ? allPages.flat().length : undefined,
    initialPageParam: 0,
  });

  const books = data?.pages.flat() ?? [];

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

  if (showScheduler) {
    return (
      <SchedulerStatus onBack={() => setShowScheduler(false)} />
    );
  }

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>Story Manager</h1>
        <button className="btn-text" onClick={() => setShowConfigs(true)}>Cleaning Configs</button>
        <button className="btn-text" onClick={() => setShowScheduler(true)}>Scheduler</button>
        <button
          className="btn-text"
          onClick={() => reprocessMutation.mutate()}
          disabled={reprocessMutation.isPending}
        >
          {reprocessMutation.isPending ? "Reprocessing..." : "Reprocess All"}
        </button>
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
      <BookList
        books={books}
        onEdit={setEditingBook}
        fetchNextPage={fetchNextPage}
        hasNextPage={hasNextPage}
        isFetchingNextPage={isFetchingNextPage}
      />
    </div>
  );
}

export default App;
