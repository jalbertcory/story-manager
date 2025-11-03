import React, { useState, useEffect } from "react";

function EpubEditor({ book, onBack }) {
  const [chapters, setChapters] = useState([]);
  const [removedChapters, setRemovedChapters] = useState(
    book.removed_chapters || [],
  );
  const [divSelectors, setDivSelectors] = useState(
    (book.div_selectors || []).join(", "),
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchChapters = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/books/${book.id}/chapters`);
        if (!res.ok) {
          throw new Error("Failed to fetch chapters");
        }
        const data = await res.json();
        setChapters(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    fetchChapters();
  }, [book.id]);

  const handleToggleChapter = (filename) => {
    const newRemovedChapters = removedChapters.includes(filename)
      ? removedChapters.filter((f) => f !== filename)
      : [...removedChapters, filename];
    setRemovedChapters(newRemovedChapters);
  };

  const handleSaveChanges = async () => {
    try {
      await fetch(`/api/books/${book.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          removed_chapters: removedChapters,
          div_selectors: divSelectors
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        }),
      });
    } catch (err) {
      setError("Failed to save changes.");
      console.error(err);
    }
  };

  const handleProcessBook = async () => {
    await handleSaveChanges(); // Save first
    try {
      const res = await fetch(`/api/books/${book.id}/process`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Processing failed.");
      onBack();
    } catch (err) {
      setError("Failed to process book.");
      console.error(err);
    }
  };

  return (
    <div>
      <h2>EPUB Editor for {book.title}</h2>
      <button onClick={onBack}>Back to List</button>

      <h3>Chapters</h3>
      {loading && <p>Loading chapters...</p>}
      {error && <p className="error">{error}</p>}
      <ul>
        {chapters.map((chapter) => (
          <li
            key={chapter.filename}
            style={{
              textDecoration: removedChapters.includes(chapter.filename)
                ? "line-through"
                : "none",
            }}
          >
            <input
              type="checkbox"
              checked={!removedChapters.includes(chapter.filename)}
              onChange={() => handleToggleChapter(chapter.filename)}
            />
            {chapter.title}
          </li>
        ))}
      </ul>

      <h3>Div Selectors to Remove (comma-separated)</h3>
      <input
        type="text"
        placeholder="e.g., note, author-note"
        value={divSelectors}
        onChange={(e) => setDivSelectors(e.target.value)}
        style={{ width: "100%", marginBottom: "10px" }}
      />

      <button onClick={handleSaveChanges}>Save Changes</button>
      <button onClick={handleProcessBook}>Process Book</button>
    </div>
  );
}

export default EpubEditor;
