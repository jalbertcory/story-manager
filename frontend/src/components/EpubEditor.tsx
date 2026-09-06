import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { getBookChapters, updateBook, processBook } from "../api/books";
import type { components } from "../api/schema";

function EpubEditor({
  book,
  onBack,
}: {
  book: components["schemas"]["Book"];
  onBack: () => void;
}) {
  const queryClient = useQueryClient();
  const [removedChapters, setRemovedChapters] = useState<string[]>([]);
  const [contentSelectors, setContentSelectors] = useState("");

  useEffect(() => {
    setRemovedChapters(book.removed_chapters || []);
    setContentSelectors((book.content_selectors || []).join(", "));
  }, [book]);

  const {
    data: chapters = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["chapters", book.id],
    queryFn: () => getBookChapters(book.id),
  });

  const saveMutation = useMutation({
    mutationFn: ({
      id,
      ...data
    }: {
      id: number;
      removed_chapters: string[];
      content_selectors: string[];
    }) => updateBook(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
    },
  });

  const processMutation = useMutation({
    mutationFn: ({ id }: { id: number }) => processBook(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      onBack();
    },
  });

  const handleToggleChapter = (filename: string) => {
    const newRemovedChapters = removedChapters.includes(filename)
      ? removedChapters.filter((f) => f !== filename)
      : [...removedChapters, filename];
    setRemovedChapters(newRemovedChapters);
  };

  const getChanges = () => ({
    id: book.id,
    removed_chapters: removedChapters,
    content_selectors: contentSelectors
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

      <h3>Content Selectors to Remove (comma-separated)</h3>
      <input
        type="text"
        placeholder="e.g., div.note, span.author-note"
        value={contentSelectors}
        onChange={(e) => setContentSelectors(e.target.value)}
        style={{ width: "100%", marginBottom: "10px" }}
      />

      <button onClick={handleSaveChanges} disabled={saveMutation.isPending}>
        {saveMutation.isPending ? "Saving..." : "Save Changes"}
      </button>
      <button
        onClick={() => {
          void handleProcessBook();
        }}
        disabled={saveMutation.isPending || processMutation.isPending}
      >
        {processMutation.isPending
          ? "Queueing..."
          : saveMutation.isPending
            ? "Saving..."
            : "Queue Book Processing"}
      </button>

      {saveMutation.isError && (
        <p className="error">Save failed: {saveMutation.error.message}</p>
      )}
      {processMutation.isError && (
        <p className="error">Process failed: {processMutation.error.message}</p>
      )}
    </div>
  );
}

export default EpubEditor;
