import { useState, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

const uploadEpubs = async (files) => {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  const res = await fetch("/api/books/upload_epubs", {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || "File upload failed");
  }
  return res.json(); // List<EpubUploadResult>
};

const addWebNovel = async (url) => {
  const res = await fetch("/api/books/add_web_novel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || "Failed to add web novel");
  }
  return res.json();
};

const formatImportSummary = ({ totalProcessed, succeeded, skipped, failed }) => {
  if (totalProcessed === 0) {
    return "No books were processed.";
  }

  const parts = [`Imported ${succeeded.length} of ${totalProcessed} book${totalProcessed === 1 ? "" : "s"}.`];
  if (skipped.length > 0) {
    parts.push(`${skipped.length} skipped.`);
  }
  if (failed.length > 0) {
    parts.push(`${failed.length} failed.`);
  }
  return parts.join(" ");
};

const formatSkippedMessage = (error) => {
  const message = error || "Skipped";
  const duplicateMatch = message.match(/A book with title '(.+)' by '(.+)' already exists/);
  if (duplicateMatch) {
    const [, title, author] = duplicateMatch;
    return `"${title}" by ${author} is already in your library.`;
  }
  return message;
};

function AddBook() {
  const queryClient = useQueryClient();
  const [files, setFiles] = useState([]);
  const [urls, setUrls] = useState([""]);
  const [dragging, setDragging] = useState(false);
  const [pending, setPending] = useState(false);
  const [results, setResults] = useState(null);
  const fileInputRef = useRef(null);

  const handleFileChange = (e) => {
    setFiles((prev) => [...prev, ...Array.from(e.target.files)]);
    e.target.value = "";
  };

  const removeFile = (index) => setFiles((prev) => prev.filter((_, i) => i !== index));

  const handleUrlChange = (index, value) =>
    setUrls((prev) => prev.map((u, i) => (i === index ? value : u)));

  const addUrlField = () => setUrls((prev) => [...prev, ""]);

  const removeUrlField = (index) => setUrls((prev) => prev.filter((_, i) => i !== index));

  const handleDragOver = (e) => {
    e.preventDefault();
    setDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const dropped = Array.from(e.dataTransfer.files).filter((f) => {
      const lower = f.name.toLowerCase();
      return lower.endsWith(".epub") || lower.endsWith(".zip");
    });
    setFiles((prev) => [...prev, ...dropped]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const activeUrls = urls.filter((u) => u.trim());
    if (files.length === 0 && activeUrls.length === 0) return;

    setPending(true);
    setResults(null);

    const succeeded = [];
    const skipped = [];
    const failed = [];

    if (files.length > 0) {
      try {
        const epubResults = await uploadEpubs(files);
        for (const r of epubResults) {
          if (r.status === "success") {
            succeeded.push(r.book?.title || r.filename);
          } else if (r.status === "skipped") {
            skipped.push({ name: r.filename, error: formatSkippedMessage(r.error) });
          } else {
            failed.push({ name: r.filename, error: r.error || "Upload failed" });
          }
        }
      } catch (err) {
        for (const file of files) {
          failed.push({ name: file.name, error: err.message });
        }
      }
    }

    for (const url of activeUrls) {
      try {
        const book = await addWebNovel(url);
        succeeded.push(book.title || url);
      } catch (err) {
        failed.push({ name: url, error: err.message });
      }
    }

    queryClient.invalidateQueries({ queryKey: ["books"] });
    setFiles([]);
    setUrls([""]);
    setPending(false);
    setResults({ succeeded, skipped, failed, totalProcessed: succeeded.length + skipped.length + failed.length });
  };

  const total = files.length + urls.filter((u) => u.trim()).length;

  return (
    <div className="add-book-container">
      <h2>Add Books</h2>
      <form onSubmit={handleSubmit}>
        <div
          id="drop-zone"
          className={`drop-zone ${dragging ? "dragging" : ""}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current.click()}
        >
          {files.length > 0 ? (
            <ul className="file-list" onClick={(e) => e.stopPropagation()}>
              {files.map((f, i) => (
                <li key={i}>
                  <span>{f.name}</span>
                  <button type="button" className="remove-btn" onClick={() => removeFile(i)}>
                    ×
                  </button>
                </li>
              ))}
              <li className="add-more-hint">Click or drop to add more EPUBs or ZIPs</li>
            </ul>
          ) : (
            <p>Drag & drop EPUB or ZIP files here, or click to select</p>
          )}
          <input
            id="file-upload"
            type="file"
            accept=".epub,.zip"
            multiple
            onChange={handleFileChange}
            ref={fileInputRef}
            style={{ display: "none" }}
          />
        </div>

        <div className="form-group">
          <label>Or add by URL:</label>
          {urls.map((url, i) => (
            <div key={i} className="url-row">
              <input
                type="text"
                placeholder="Enter URL"
                value={url}
                onChange={(e) => handleUrlChange(i, e.target.value)}
              />
              {urls.length > 1 && (
                <button type="button" className="remove-btn" onClick={() => removeUrlField(i)}>
                  ×
                </button>
              )}
            </div>
          ))}
          <button type="button" className="add-url-btn" onClick={addUrlField}>
            + Add URL
          </button>
        </div>

        <button type="submit" disabled={pending || total === 0}>
          {pending ? "Adding..." : total > 1 ? `Add ${total} Books` : "Add Book"}
        </button>
      </form>

      {results && (
        <div className="add-results">
          <p className="summary">{formatImportSummary(results)}</p>
          {results.succeeded.length > 0 && (
            <p className="success">
              Added: {results.succeeded.length} book{results.succeeded.length === 1 ? "" : "s"}.
            </p>
          )}
          {results.skipped.length > 0 && (
            <div className="result-group">
              <p className="skipped-summary">
                Skipped: {results.skipped.length} book{results.skipped.length === 1 ? "" : "s"}.
              </p>
              <ul className="error-list">
                {results.skipped.map((f, i) => (
                  <li key={i} className="skipped">
                    <strong>{f.name}</strong>: {f.error}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {results.failed.length > 0 && (
            <div className="result-group">
              <p className="error-summary">
                Failed: {results.failed.length} book{results.failed.length === 1 ? "" : "s"}.
              </p>
              <ul className="error-list">
                {results.failed.map((f, i) => (
                  <li key={i} className="error">
                    <strong>{f.name}</strong>: {f.error}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default AddBook;
