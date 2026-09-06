import type { Book, BookSectionChange } from "../types";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getBookCleanedChapters, refreshBook } from "../api/books";
import { getLibraryBookInfo } from "../api/library";
import { getApiCoverUrl } from "../api/covers";
import { sanitizeChapterHtml } from "../lib/chapterHtml";
import UniverseMembership from "./UniverseMembership";
import { libraryPath } from "../lib/library";

export default function BookOverview({
  book,
  onBack,
  onSection,
  backLabel = "Back to library",
}: {
  book: Book;
  onBack: () => void;
  onSection: BookSectionChange;
  backLabel?: string;
}) {
  const client = useQueryClient();
  const [chaptersOpen, setChaptersOpen] = useState(false);
  const [chapterSearch, setChapterSearch] = useState("");
  const info = useQuery({
    queryKey: ["library-book-info", book.id],
    queryFn: () => getLibraryBookInfo(book.id),
  });
  const chapters = useQuery({
    queryKey: ["cleaned-chapters", book.id],
    queryFn: () => getBookCleanedChapters(book.id),
    enabled: chaptersOpen && Boolean(book.current_path),
  });
  const refresh = useMutation({
    mutationFn: () => refreshBook(book.id),
    onSuccess: (updated) => {
      client.setQueryData(["book", book.id], updated);
      void client.invalidateQueries({ queryKey: ["active-processing-jobs"] });
    },
  });
  const checking = ["queued", "processing"].includes(book.refresh_status || "");
  const data = info.data;
  return (
    <section className="book-overview">
      <nav className="breadcrumbs" aria-label="Book location">
        <button className="btn-text" onClick={onBack}>
          ← {backLabel}
        </button>
        {data?.universe_name && (
          <>
            <span>/</span>
            <a
              href={libraryPath({
                group: "universe",
                universe: data.universe_id,
                universeName: data.universe_name,
              })}
            >
              {data.universe_name}
            </a>
          </>
        )}
        {book.series && (
          <>
            <span>/</span>
            <a
              href={libraryPath({
                group: data?.universe_id ? "universe" : "series",
                series: book.series,
                ...(data?.universe_id
                  ? {
                      universe: data.universe_id,
                      universeName: data.universe_name,
                    }
                  : {}),
              })}
            >
              {book.series}
            </a>
          </>
        )}
      </nav>
      <div className="book-hero">
        {book.cover_path ? (
          <img
            className="book-hero-cover"
            src={getApiCoverUrl(book.id)}
            alt={`${book.title} cover`}
          />
        ) : (
          <div className="book-hero-cover cover-placeholder">No cover</div>
        )}
        <div className="book-hero-copy">
          <h2>{book.title}</h2>
          <p>{book.author || "Unknown author"}</p>
          {book.series && (
            <p className="hint">
              {book.series}
              {book.series_index != null ? ` · Book ${book.series_index}` : ""}
            </p>
          )}
          <div className="group-formats">
            {book.current_path && <span>EPUB</span>}
            {data?.audio_playable && <span>Audiobook</span>}
            {book.source_type === "web" && <span>Web novel</span>}
          </div>
          <div className="workspace-actions">
            {book.current_path && (
              <a
                className="btn-primary"
                href={`/api/books/${book.id}/download`}
                download
              >
                Download EPUB
              </a>
            )}
            {data?.audio_playable && (
              <button
                className="btn-primary"
                onClick={() => onSection("audiobooks", "listen-read")}
              >
                Listen
              </button>
            )}
            <button onClick={() => onSection("details")}>Edit details</button>
          </div>
        </div>
      </div>
      {!book.current_path && (
        <p className="workspace-notice">
          {book.download_status === "pending"
            ? "Your book is being imported."
            : "This book does not have a downloadable EPUB yet."}
        </p>
      )}
      {info.error && (
        <p className="error" role="alert">
          Could not load audiobook and universe information:{" "}
          {info.error.message}
        </p>
      )}
      {book.notes && (
        <div className="overview-section">
          <h3>Notes</h3>
          <p className="book-notes">{book.notes}</p>
        </div>
      )}
      <details
        className="workspace-disclosure"
        onToggle={(e) => setChaptersOpen(e.currentTarget.open)}
      >
        <summary>Browse chapters</summary>
        {chapters.isLoading && <p role="status">Loading chapters…</p>}
        {chapters.error && (
          <p role="alert" className="error">
            {chapters.error.message}
          </p>
        )}
        {!book.current_path ? (
          <p>Chapters will appear after the book is imported.</p>
        ) : (
          <>
            <input
              aria-label="Search chapters"
              placeholder="Find a chapter"
              value={chapterSearch}
              onChange={(e) => setChapterSearch(e.target.value)}
            />
            {(chapters.data || [])
              .filter((chapter) =>
                chapter.title
                  .toLowerCase()
                  .includes(chapterSearch.toLowerCase()),
              )
              .map((chapter) => (
                <details
                  className="chapter-preview-item"
                  key={chapter.filename}
                >
                  <summary>{chapter.title}</summary>
                  <div
                    className="chapter-preview-content"
                    dangerouslySetInnerHTML={{
                      __html: sanitizeChapterHtml(chapter.content),
                    }}
                  />
                </details>
              ))}
            {chapters.data?.length === 0 && <p>No chapters found.</p>}
          </>
        )}
      </details>
      <div className="overview-section">
        <div>
          <h3>Audiobooks</h3>
          <p className="hint">
            Listen to an edition, import narration, or open AI production.
          </p>
        </div>
        <button onClick={() => onSection("audiobooks", "sources")}>
          Manage audiobooks
        </button>
      </div>
      {book.source_type === "web" && (
        <div className="overview-section">
          <div>
            <h3>Web source</h3>
            <p className="hint">
              <a href="/updates">View chapter changes and source checks</a>
            </p>
          </div>
          <button
            disabled={checking || refresh.isPending}
            onClick={() => refresh.mutate()}
          >
            {checking ? "Check queued / running" : "Check for updates"}
          </button>
          {refresh.error && (
            <p role="alert" className="error">
              {refresh.error.message}
            </p>
          )}
          {refresh.isSuccess && <p role="status">Source check queued.</p>}
        </div>
      )}
      <details className="workspace-disclosure">
        <summary>Universe membership</summary>
        <UniverseMembership
          key={`${book.id}-${data?.universe_name}`}
          bookId={book.id}
          series={book.series}
          currentName={data?.universe_name}
        />
      </details>
      <details className="workspace-disclosure">
        <summary>Cleaning, identifiers, and recovery</summary>
        <p className="hint">
          Review cleaning rules, edit identifiers, or restore an earlier version
          of this book.
        </p>
        <button onClick={() => onSection("details")}>Open book settings</button>
      </details>
    </section>
  );
}
