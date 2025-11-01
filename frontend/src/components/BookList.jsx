import React from "react";

function BookList({ books = [], onEdit }) {
  if (!books.length) {
    return <p>No books found.</p>;
  }

  return (
    <ul className="book-list">
      {books.map((book) => (
        <li key={book.id}>
          <strong>{book.title}</strong> by {book.author}
          {book.series ? ` - ${book.series}` : ""}
          <button onClick={() => onEdit(book.id)}>Edit</button>
        </li>
      ))}
    </ul>
  );
}

export default BookList;
