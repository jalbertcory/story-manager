import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import "./App.css";
import BookList from "./components/BookList";
import EpubEditor from "./components/EpubEditor";
import AddBook from "./components/AddBook.jsx";

const fetchBooks = async ({ queryKey }) => {
  const [_key, { author, series }] = queryKey;

  let endpoint = "/api/books";
  if (author) {
    endpoint = `/api/books/search/author/${encodeURIComponent(author)}`;
  } else if (series) {
    endpoint = `/api/books/search/series/${encodeURIComponent(series)}`;
  }

  const res = await fetch(endpoint);
  if (!res.ok) {
    throw new Error("Failed to fetch books");
  }
  return res.json();
};

function App() {
  const [author, setAuthor] = useState("");
  const [series, setSeries] = useState("");
  const [searchParams, setSearchParams] = useState({ author: "", series: "" });
  const [editingBook, setEditingBook] = useState(null);

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
    setSearchParams({ author: author.trim(), series: series.trim() });
  };

  const handleClearSearch = () => {
    setAuthor("");
    setSeries("");
    setSearchParams({ author: "", series: "" });
  };

  if (editingBook) {
    return (
      <EpubEditor book={editingBook} onBack={() => setEditingBook(null)} />
    );
  }

  return (
    <div className="app-container">
      <h1>Story Manager</h1>
      <div className="search-controls">
        <input
          type="text"
          placeholder="Search by author"
          value={author}
          onChange={(e) => setAuthor(e.target.value)}
        />
        <input
          type="text"
          placeholder="Search by series"
          value={series}
          onChange={(e) => setSeries(e.target.value)}
        />
        <button onClick={handleSearch}>Search</button>
        <button onClick={handleClearSearch}>Clear</button>
      </div>
      <AddBook />
      {isLoading && <p>Loading...</p>}
      {error && <p className="error">{error.message}</p>}
      <BookList books={books} onEdit={setEditingBook} />
    </div>
  );
}

export default App;
