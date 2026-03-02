import React, { useState, useRef, useEffect } from "react";

const NO_COVER_SVG =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='250'%3E%3Crect width='200' height='250' fill='%23e0e0e0'/%3E%3Ctext x='100' y='125' dominant-baseline='middle' text-anchor='middle' font-family='sans-serif' font-size='14' fill='%23888'%3ENo Cover%3C/text%3E%3C/svg%3E";

function BookCard({ book, onEdit }) {
  const isPending = book.download_status === "pending";
  const isError = book.download_status === "error";

  const handleCoverError = (e) => {
    e.target.onerror = null;
    e.target.src = NO_COVER_SVG;
  };

  const formattedDate = book.updated_at
    ? new Date(book.updated_at).toLocaleDateString()
    : null;

  let coverContent;
  if (isPending) {
    coverContent = (
      <div className="book-cover book-cover--placeholder">
        <div className="spinner" />
        <span>Downloading…</span>
      </div>
    );
  } else if (isError) {
    coverContent = (
      <div className="book-cover book-cover--placeholder book-cover--error">
        <span>⚠ Download failed</span>
      </div>
    );
  } else {
    coverContent = (
      <img
        src={`/api/covers/${book.id}`}
        alt={`${book.title} cover`}
        className="book-cover"
        onError={handleCoverError}
      />
    );
  }

  return (
    <div
      className={`book-card${isPending ? " book-card--pending" : ""}${isError ? " book-card--error" : ""}`}
      onClick={isPending ? undefined : () => onEdit(book)}
    >
      {coverContent}
      <div className="book-info">
        <h3 title={isPending || isError ? book.source_url : book.title}>
          {isPending ? "Downloading…" : isError ? "Download failed" : book.title}
        </h3>
        {!isPending && <p className="book-author">{book.author}</p>}
        {!isPending && book.series && <p className="book-series">Series: {book.series}</p>}
        {!isPending && (
          <p className="book-words">
            {book.current_word_count != null
              ? book.current_word_count.toLocaleString() + " words"
              : "—"}
          </p>
        )}
        {formattedDate && !isPending && <p className="book-updated">Updated: {formattedDate}</p>}
        {book.source_type === "web" && !isPending && <span className="badge-web">Web</span>}
        {isError && book.source_url && (
          <p className="book-error-url" title={book.source_url}>
            {book.source_url.length > 40 ? book.source_url.slice(0, 40) + "…" : book.source_url}
          </p>
        )}
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

function BookList({ books = [], onEdit, fetchNextPage, hasNextPage, isFetchingNextPage }) {
  const sentinelRef = useRef(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage();
        }
      },
      { threshold: 0.1 }
    );
    if (sentinelRef.current) observer.observe(sentinelRef.current);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  if (!books.length) {
    return <p>No books found.</p>;
  }

  // Group books: series → alphabetical by series then title; standalone at bottom
  const seriesMap = {};
  const standalone = [];

  for (const book of books) {
    if (book.series && !book.download_status) {
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
      <div ref={sentinelRef} style={{ height: 1 }} />
      {isFetchingNextPage && <p className="loading-more">Loading more…</p>}
    </div>
  );
}

export default BookList;
