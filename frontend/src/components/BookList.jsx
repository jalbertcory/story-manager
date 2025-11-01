import React from "react";

function BookList({ books = [], onEdit }) {
  if (!books.length) {
    return <p>No books found.</p>;
  }

  return (
    <table className="book-list-table">
      <thead>
        <tr>
          <th>Title</th>
          <th>Author</th>
          <th>Series</th>
          <th>Master Word Count</th>
          <th>Current Word Count</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {books.map((book) => (
          <tr key={book.id}>
            <td>{book.title}</td>
            <td>{book.author}</td>
            <td>{book.series}</td>
            <td>{book.master_word_count}</td>
            <td>{book.current_word_count}</td>
            <td>
              <button onClick={() => onEdit(book)}>Edit</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default BookList;
