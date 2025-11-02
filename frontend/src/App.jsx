import { useState, useEffect } from "react";
import "./App.css";
import BookList from "./components/BookList";
import AddBook from "./components/AddBook";

function App() {
  const [books, setBooks] = useState([]);
  const [author, setAuthor] = useState("");
  const [series, setSeries] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchBooks = async (endpoint) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(endpoint);
      if (!res.ok) {
        throw new Error("Failed to fetch books");
      }
      const data = await res.json();
      setBooks(data);
    } catch (err) {
      setError(err.message);
      setBooks([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBooks("/api/books");
  }, []);

  const handleSearch = () => {
    const authorTrim = author.trim();
    const seriesTrim = series.trim();
    if (authorTrim) {
      fetchBooks(`/api/books/search/author/${encodeURIComponent(authorTrim)}`);
    } else if (seriesTrim) {
      fetchBooks(`/api/books/search/series/${encodeURIComponent(seriesTrim)}`);
    } else {
      fetchBooks("/api/books");
    }
  };

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
      </div>
      <AddBook onBookAdded={() => fetchBooks("/api/books")} />
      {loading && <p>Loading...</p>}
      {error && <p className="error">{error}</p>}
      <BookList books={books} />
    </div>
  );
}

export default App;
