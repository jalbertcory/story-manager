import { useMemo } from "react";

import { sanitizeChapterHtml } from "../lib/chapterHtml";

function BookSettingsChapters({
  book,
  chapters,
  cleanedChapters,
  chaptersLoading,
  cleanedChaptersLoading,
  chaptersExpanded,
  setChaptersExpanded,
  chapterPreviewMode,
  setChapterPreviewMode,
  chapterSearch,
  setChapterSearch,
  removedChapters,
  toggleChapter,
  previewedChapter,
  toggleChapterPreview,
}) {
  const activeChapters =
    chapterPreviewMode === "cleaned" ? cleanedChapters : chapters;
  const activeChaptersLoading =
    chapterPreviewMode === "cleaned" ? cleanedChaptersLoading : chaptersLoading;

  const filteredChapters = useMemo(() => {
    if (!chapterSearch.trim()) return activeChapters;
    const query = chapterSearch.toLowerCase();
    return activeChapters.filter((chapter) =>
      chapter.title.toLowerCase().includes(query),
    );
  }, [activeChapters, chapterSearch]);

  return (
    <section className="settings-section">
      <div className="chapter-section-header">
        <h3>
          Chapters
          {activeChapters.length > 0 && (
            <span className="chapter-count"> ({activeChapters.length})</span>
          )}
        </h3>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          {chaptersExpanded && (
            <select
              value={chapterPreviewMode}
              onChange={(event) => setChapterPreviewMode(event.target.value)}
              className="chapter-preview-mode-select"
            >
              <option value="original">Original</option>
              <option value="cleaned">Cleaned</option>
            </select>
          )}
          <button
            className="btn-text"
            onClick={() => setChaptersExpanded((expanded) => !expanded)}
            disabled={activeChaptersLoading}
          >
            {chaptersExpanded ? "▲ Collapse" : "▼ Expand"}
          </button>
        </div>
      </div>

      {activeChaptersLoading && (
        <p className="hint" style={{ marginTop: "0.5rem" }}>
          Loading chapters…
        </p>
      )}

      {!book.immutable_path && (
        <p className="hint" style={{ marginTop: "0.5rem" }}>
          This web import does not have EPUB files yet. Retry the source
          download or delete the placeholder entry.
        </p>
      )}

      {chaptersExpanded && !activeChaptersLoading && book.immutable_path && (
        <>
          {chapters.length > 10 && (
            <input
              className="chapter-search"
              type="text"
              placeholder="Filter chapters…"
              value={chapterSearch}
              onChange={(event) => setChapterSearch(event.target.value)}
            />
          )}
          <div className="chapter-list-scroll">
            <ul className="chapter-list">
              {filteredChapters.length === 0 ? (
                <li className="chapter-no-results">
                  No chapters match your search.
                </li>
              ) : (
                filteredChapters.map((chapter) => {
                  const isRemoved =
                    chapterPreviewMode === "original" &&
                    removedChapters.includes(chapter.filename);
                  const isPreviewed = previewedChapter === chapter.filename;
                  return (
                    <li
                      key={chapter.filename}
                      className={isRemoved ? "removed" : ""}
                    >
                      <div className="chapter-row">
                        {chapterPreviewMode === "original" ? (
                          <label>
                            <input
                              type="checkbox"
                              checked={!isRemoved}
                              onChange={() => toggleChapter(chapter.filename)}
                            />
                            {chapter.title}
                          </label>
                        ) : (
                          <span>{chapter.title}</span>
                        )}
                        <button
                          className="btn-text chapter-preview-toggle"
                          onClick={() => toggleChapterPreview(chapter.filename)}
                        >
                          {isPreviewed ? "▲ Hide" : "▼ Preview"}
                        </button>
                      </div>
                      {isPreviewed && (
                        <div
                          className="chapter-preview"
                          dangerouslySetInnerHTML={{
                            __html: sanitizeChapterHtml(chapter.content),
                          }}
                        />
                      )}
                    </li>
                  );
                })
              )}
            </ul>
          </div>
        </>
      )}
    </section>
  );
}

export default BookSettingsChapters;
