import React from "react";

function BookList({ books = [], onEdit }) {
  if (!books.length) {
    return <p>No books found.</p>;
  }

  const handleCoverError = (e) => {
    e.target.onerror = null;
    e.target.src = "https://via.placeholder.com/200x250?text=No+Cover";
  };

  return (
    <div className="book-grid">
      {books.map((book) => (
        <div key={book.id} className="book-card" onClick={() => onEdit(book)}>
          <img
            src={`/api/covers/${book.id}`}
            alt={`${book.title} cover`}
            className="book-cover"
            onError={handleCoverError}
          />
          <div className="book-info">
            <h3>{book.title}</h3>
            <p>{book.author}</p>
            {book.series && <p>Series: {book.series}</p>}
            <p>Master: {book.master_word_count}</p>
            <p>Current: {book.current_word_count}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

export default BookList;
