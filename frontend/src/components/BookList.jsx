import React from 'react'

function BookList({ books = [] }) {
  if (!books.length) {
    return <p>No books found.</p>
  }

  return (
    <ul className="book-list">
      {books.map((book) => (
        <li key={book.id}>
          <strong>{book.title}</strong> by {book.author}
          {book.series ? ` - ${book.series}` : ''}
        </li>
      ))}
    </ul>
  )
}

export default BookList
