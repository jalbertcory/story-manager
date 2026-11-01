import { useEffect, useState } from "react";
import type { CatalogBook } from "../../types";
import {
  bookLabel,
  normalizeMatchText,
  scoreBookSearch,
} from "../../lib/filenameMatching";

export default function BookCombobox({
  books,
  selectedBookId,
  onSelect,
}: {
  books: CatalogBook[];
  selectedBookId: number | null;
  onSelect: (bookId: number | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const selectedBook = books.find((book) => book.id === selectedBookId);
  const selectedLabel = selectedBook ? bookLabel(selectedBook) : "";
  const normalizedQuery = normalizeMatchText(query);
  const queryTokens = normalizedQuery.split(" ").filter(Boolean);
  const showingSelectedLabel = selectedLabel && query === selectedLabel;
  const options = (
    !normalizedQuery || showingSelectedLabel
      ? books
      : books
          .filter((book) => {
            const searchable = normalizeMatchText(bookLabel(book));
            return queryTokens.every((token) => searchable.includes(token));
          })
          .sort(
            (left, right) =>
              scoreBookSearch(right, normalizedQuery) -
                scoreBookSearch(left, normalizedQuery) ||
              bookLabel(left).localeCompare(bookLabel(right)),
          )
  ).slice(0, 20);

  useEffect(() => {
    if (selectedBook) {
      setQuery(bookLabel(selectedBook));
    }
  }, [selectedBook]);

  useEffect(() => {
    setActiveIndex(-1);
  }, [query]);

  const chooseBook = (book: CatalogBook) => {
    setQuery(bookLabel(book));
    setOpen(false);
    onSelect(book.id);
  };

  return (
    <div
      className="import-book-combobox"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setOpen(false);
        }
      }}
    >
      <label htmlFor="audiobook-book-search">Attach narration to</label>
      <input
        id="audiobook-book-search"
        type="search"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls="audiobook-book-options"
        aria-activedescendant={
          open && options[activeIndex]
            ? `audiobook-book-option-${options[activeIndex].id}`
            : undefined
        }
        placeholder="Search by title or author"
        autoComplete="off"
        value={query}
        onFocus={(event) => {
          event.currentTarget.select();
          setOpen(true);
        }}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
          if (selectedBookId) onSelect(null);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
            setActiveIndex((current) =>
              current < 0 ? 0 : Math.min(current + 1, options.length - 1),
            );
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
            setActiveIndex((current) => Math.max(current - 1, 0));
          } else if (event.key === "Enter" && open && options[activeIndex]) {
            event.preventDefault();
            chooseBook(options[activeIndex]);
          } else if (event.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {open && (
        <ul
          id="audiobook-book-options"
          className="import-book-options"
          role="listbox"
          aria-label="Library book matches"
        >
          {options.map((book, index) => (
            <li
              id={`audiobook-book-option-${book.id}`}
              key={book.id}
              role="option"
              aria-selected={book.id === selectedBookId}
              className={
                index === activeIndex ? "import-book-option--active" : ""
              }
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => chooseBook(book)}
            >
              <strong>{book.title}</strong>
              <span>{book.author || "Unknown author"}</span>
            </li>
          ))}
          {!options.length && (
            <li className="import-book-options-empty">No matching books</li>
          )}
        </ul>
      )}
    </div>
  );
}
