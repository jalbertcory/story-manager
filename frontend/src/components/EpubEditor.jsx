import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

const fetchChapters = async ({ queryKey }) => {
  const [_key, bookId] = queryKey;
  const res = await fetch(`/api/books/${bookId}/chapters`);
  if (!res.ok) {
    throw new Error("Failed to fetch chapters");
  }
  return res.json();
};

const updateBook = async ({ id, removed_chapters, div_selectors }) => {
  const res = await fetch(`/api/books/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ removed_chapters, div_selectors }),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || "Failed to save changes");
  }
  return res.json();
};

const processBook = async ({ id }) => {
  const res = await fetch(`/api/books/${id}/process`, { method: "POST" });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || "Processing failed");
  }
  return res.json();
};

function EpubEditor({ book, onBack }) {
  const queryClient = useQueryClient();
  const [removedChapters, setRemovedChapters] = useState([]);
  const [divSelectors, setDivSelectors] = useState("");

  useEffect(() => {
    setRemovedChapters(book.removed_chapters || []);
    setDivSelectors((book.div_selectors || []).join(", "));
  }, [book]);

  const {
    data: chapters = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["chapters", book.id],
    queryFn: fetchChapters,
  });

  const saveMutation = useMutation({
    mutationFn: updateBook,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["books"] });
    },
  });

  const processMutation = useMutation({
    mutationFn: processBook,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["books"] });
      onBack();
    },
  });

  const handleToggleChapter = (filename) => {
    const newRemovedChapters = removedChapters.includes(filename)
      ? removedChapters.filter((f) => f !== filename)
      : [...removedChapters, filename];
    setRemovedChapters(newRemovedChapters);
  };

  const getChanges = () => ({
    id: book.id,
    removed_chapters: removedChapters,
    div_selectors: divSelectors
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  });

  const handleSaveChanges = () => {
    saveMutation.mutate(getChanges());
  };

  const handleProcessBook = async () => {
    try {
      await saveMutation.mutateAsync(getChanges());
      await processMutation.mutateAsync({ id: book.id });
    } catch (err) {
      // Errors are handled by the mutation hooks
      console.error("Save or process failed", err);
    }
  };

  return (
    <div>
      <h2>EPUB Editor for {book.title}</h2>
      <button onClick={onBack}>Back to List</button>

      <h3>Chapters</h3>
      {isLoading && <p>Loading chapters...</p>}
      {error && <p className="error">{error.message}</p>}
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

      <button onClick={handleSaveChanges} disabled={saveMutation.isPending}>
        {saveMutation.isPending ? "Saving..." : "Save Changes"}
      </button>
      <button
        onClick={handleProcessBook}
        disabled={saveMutation.isPending || processMutation.isPending}
      >
        {processMutation.isPending
          ? "Processing..."
          : saveMutation.isPending
            ? "Saving..."
            : "Process Book"}
      </button>

      {saveMutation.isError && (
        <p className="error">Save failed: {saveMutation.error.message}</p>
      )}
      {processMutation.isError && (
        <p className="error">
          Process failed: {processMutation.error.message}
        </p>
      )}
    </div>
  );
}

export default EpubEditor;
