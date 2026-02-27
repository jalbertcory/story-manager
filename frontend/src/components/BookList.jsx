import React, { useState } from "react";

function BookCard({ book, onEdit }) {
  const handleCoverError = (e) => {
    e.target.onerror = null;
    e.target.src = "https://via.placeholder.com/200x250?text=No+Cover";
  };

  const formattedDate = book.updated_at
    ? new Date(book.updated_at).toLocaleDateString()
    : null;

  return (
    <div className="book-card" onClick={() => onEdit(book)}>
      <img
        src={`/api/covers/${book.id}`}
        alt={`${book.title} cover`}
        className="book-cover"
        onError={handleCoverError}
      />
      <div className="book-info">
        <h3>{book.title}</h3>
        <p className="book-author">{book.author}</p>
        {book.series && <p className="book-series">Series: {book.series}</p>}
        <p className="book-words">
          {book.current_word_count != null
            ? book.current_word_count.toLocaleString() + " words"
            : "—"}
        </p>
        {formattedDate && <p className="book-updated">Updated: {formattedDate}</p>}
        {book.source_type === "web" && <span className="badge-web">Web</span>}
      </div>
    </div>
  );
}

function SeriesGroup({ series, books, onEdit }) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="series-group">
      <div className="series-header" onClick={() => setExpanded(!expanded)}>
        <span className="series-toggle">{expanded ? "▼" : "▶"}</span>
        <span className="series-name">{series}</span>
        <span className="series-count">
          {books.length} book{books.length !== 1 ? "s" : ""}
        </span>
      </div>
      {expanded && (
        <div className="book-grid">
          {books.map((book) => (
            <BookCard key={book.id} book={book} onEdit={onEdit} />
          ))}
        </div>
      )}
    </div>
  );
}

function BookList({ books = [], onEdit }) {
  if (!books.length) {
    return <p>No books found.</p>;
  }

  // Group books: series → alphabetical by series then title; standalone at bottom
  const seriesMap = {};
  const standalone = [];

  for (const book of books) {
    if (book.series) {
      if (!seriesMap[book.series]) {
        seriesMap[book.series] = [];
      }
      seriesMap[book.series].push(book);
    } else {
      standalone.push(book);
    }
  }

  const sortedSeries = Object.keys(seriesMap).sort();

  return (
    <div className="book-list">
      {sortedSeries.map((series) => (
        <SeriesGroup
          key={series}
          series={series}
          books={seriesMap[series]}
          onEdit={onEdit}
        />
      ))}
      {standalone.length > 0 && (
        <div className="book-grid">
          {standalone.map((book) => (
            <BookCard key={book.id} book={book} onEdit={onEdit} />
          ))}
        </div>
      )}
    </div>
  );
}

export default BookList;
