import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

const fetchChapters = async ({ queryKey }) => {
  const [_key, bookId] = queryKey;
  const res = await fetch(`/api/books/${bookId}/chapters`);
  if (!res.ok) throw new Error("Failed to fetch chapters");
  return res.json();
};

const fetchMatchedConfig = async ({ queryKey }) => {
  const [_key, bookId] = queryKey;
  const res = await fetch(`/api/books/${bookId}/matched-config`);
  if (!res.ok) throw new Error("Failed to fetch matched config");
  return res.json();
};

function SelectorPills({ selectors, onChange }) {
  const [inputValue, setInputValue] = useState("");

  const addSelector = () => {
    const trimmed = inputValue.trim();
    if (trimmed && !selectors.includes(trimmed)) {
      onChange([...selectors, trimmed]);
    }
    setInputValue("");
  };

  const removeSelector = (sel) => {
    onChange(selectors.filter((s) => s !== sel));
  };

  return (
    <div className="selector-pills">
      <div className="pills">
        {selectors.map((sel) => (
          <span key={sel} className="pill">
            {sel}
            <button className="pill-remove" onClick={() => removeSelector(sel)}>
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="pill-input">
        <input
          type="text"
          placeholder="Add CSS selector, e.g. div.note"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addSelector()}
        />
        <button onClick={addSelector}>Add</button>
      </div>
    </div>
  );
}

function BookSettings({ book, onBack }) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState(book.title || "");
  const [author, setAuthor] = useState(book.author || "");
  const [series, setSeries] = useState(book.series || "");
  const [removedChapters, setRemovedChapters] = useState(book.removed_chapters || []);
  const [contentSelectors, setContentSelectors] = useState(book.content_selectors || []);

  useEffect(() => {
    setTitle(book.title || "");
    setAuthor(book.author || "");
    setSeries(book.series || "");
    setRemovedChapters(book.removed_chapters || []);
    setContentSelectors(book.content_selectors || []);
  }, [book]);

  const { data: chapters = [], isLoading: chaptersLoading } = useQuery({
    queryKey: ["chapters", book.id],
    queryFn: fetchChapters,
  });

  const { data: matchedConfig } = useQuery({
    queryKey: ["matched-config", book.id],
    queryFn: fetchMatchedConfig,
  });

  const saveMutation = useMutation({
    mutationFn: async (data) => {
      const res = await fetch(`/api/books/${book.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to save");
      }
      return res.json();
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["books"] }),
  });

  const processMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/books/${book.id}/process`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Processing failed");
      }
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["books"] });
      onBack();
    },
  });

  const refreshMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/books/${book.id}/refresh`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Refresh failed");
      }
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["books"] });
      onBack();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/books/${book.id}`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Delete failed");
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["books"] });
      onBack();
    },
  });

  const getUpdatedFields = () => ({
    title,
    author,
    series: series.trim() || null,
    removed_chapters: removedChapters,
    content_selectors: contentSelectors,
  });

  const handleSave = () => {
    saveMutation.mutate(getUpdatedFields());
  };

  const handleProcess = async () => {
    try {
      await saveMutation.mutateAsync(getUpdatedFields());
      await processMutation.mutateAsync();
    } catch (err) {
      console.error("Save or process failed", err);
    }
  };

  const handleDelete = () => {
    if (window.confirm(`Delete "${book.title}"? This cannot be undone.`)) {
      deleteMutation.mutate();
    }
  };

  const toggleChapter = (filename) => {
    setRemovedChapters((prev) =>
      prev.includes(filename) ? prev.filter((f) => f !== filename) : [...prev, filename]
    );
  };

  const isBusy =
    saveMutation.isPending ||
    processMutation.isPending ||
    refreshMutation.isPending ||
    deleteMutation.isPending;

  return (
    <div className="book-settings">
      <div className="settings-header">
        <button onClick={onBack} disabled={isBusy}>
          ← Back
        </button>
        <h2>{book.title}</h2>
      </div>

      <section className="settings-section">
        <h3>Metadata</h3>
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label>
          Author
          <input value={author} onChange={(e) => setAuthor(e.target.value)} />
        </label>
        <label>
          Series
          <input
            value={series}
            onChange={(e) => setSeries(e.target.value)}
            placeholder="Leave blank if none"
          />
        </label>
      </section>

      {matchedConfig && (
        <section className="settings-section">
          <h3>
            Inherited Cleaning Rules{" "}
            <span className="badge-config">{matchedConfig.name}</span>
          </h3>
          <p className="hint">
            These site-wide rules apply automatically and cannot be edited here.
          </p>
          {matchedConfig.chapter_selectors?.length > 0 && (
            <div>
              <strong>Chapter selectors:</strong>
              <div className="pills readonly">
                {matchedConfig.chapter_selectors.map((s) => (
                  <span key={s} className="pill">
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
          {matchedConfig.content_selectors?.length > 0 && (
            <div>
              <strong>Content selectors:</strong>
              <div className="pills readonly">
                {matchedConfig.content_selectors.map((s) => (
                  <span key={s} className="pill">
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      <section className="settings-section">
        <h3>Per-Book Content Selectors</h3>
        <p className="hint">CSS selectors for content to remove from this book only.</p>
        <SelectorPills selectors={contentSelectors} onChange={setContentSelectors} />
      </section>

      <section className="settings-section">
        <h3>Chapters</h3>
        {chaptersLoading && <p>Loading chapters...</p>}
        <ul className="chapter-list">
          {chapters.map((chapter) => (
            <li
              key={chapter.filename}
              className={removedChapters.includes(chapter.filename) ? "removed" : ""}
            >
              <label>
                <input
                  type="checkbox"
                  checked={!removedChapters.includes(chapter.filename)}
                  onChange={() => toggleChapter(chapter.filename)}
                />
                {chapter.title}
              </label>
            </li>
          ))}
        </ul>
      </section>

      <section className="settings-section settings-actions">
        <button onClick={handleSave} disabled={isBusy}>
          {saveMutation.isPending ? "Saving..." : "Save"}
        </button>
        <button onClick={handleProcess} disabled={isBusy}>
          {processMutation.isPending ? "Processing..." : "Save & Re-process"}
        </button>
        {book.source_type === "web" && (
          <button onClick={() => refreshMutation.mutate()} disabled={isBusy}>
            {refreshMutation.isPending ? "Refreshing..." : "Refresh from Source"}
          </button>
        )}
        <button className="btn-danger" onClick={handleDelete} disabled={isBusy}>
          Delete Book
        </button>
      </section>

      {saveMutation.isError && (
        <p className="error">Save failed: {saveMutation.error.message}</p>
      )}
      {processMutation.isError && (
        <p className="error">Process failed: {processMutation.error.message}</p>
      )}
      {refreshMutation.isError && (
        <p className="error">Refresh failed: {refreshMutation.error.message}</p>
      )}
      {deleteMutation.isError && (
        <p className="error">Delete failed: {deleteMutation.error.message}</p>
      )}
    </div>
  );
}

export default BookSettings;
