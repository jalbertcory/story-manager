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

function AddBook() {
  const queryClient = useQueryClient();
  const [files, setFiles] = useState([]);
  const [urls, setUrls] = useState([""]);
  const [dragging, setDragging] = useState(false);
  const [pending, setPending] = useState(false);
  const [results, setResults] = useState(null);
  const [detectingSeriesState, setDetectingSeriesState] = useState(null); // null | "pending" | { updated, series_detected }
  const fileInputRef = useRef(null);

  const handleDetectSeries = async () => {
    setDetectingSeriesState("pending");
    try {
      const res = await fetch("/api/books/detect-series", { method: "POST" });
      const data = await res.json();
      if (data.updated > 0) {
        queryClient.invalidateQueries({ queryKey: ["books"] });
      }
      setDetectingSeriesState(data);
    } catch {
      setDetectingSeriesState({ updated: 0, series_detected: [], error: true });
    }
  };

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
    const dropped = Array.from(e.dataTransfer.files).filter((f) =>
      f.name.endsWith(".epub")
    );
    setFiles((prev) => [...prev, ...dropped]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const activeUrls = urls.filter((u) => u.trim());
    if (files.length === 0 && activeUrls.length === 0) return;

    setPending(true);
    setResults(null);

    const succeeded = [];
    const failed = [];

    if (files.length > 0) {
      try {
        const epubResults = await uploadEpubs(files);
        for (const r of epubResults) {
          if (r.status === "success") {
            succeeded.push(r.book?.title || r.filename);
          } else {
            failed.push({ name: r.filename, error: r.error, skipped: r.status === "skipped" });
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
    setResults({ succeeded, failed });
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
              <li className="add-more-hint">Click or drop to add more EPUBs</li>
            </ul>
          ) : (
            <p>Drag & drop EPUB files here, or click to select</p>
          )}
          <input
            id="file-upload"
            type="file"
            accept=".epub"
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

      <div className="detect-series-row">
        <button
          type="button"
          className="detect-series-btn"
          onClick={handleDetectSeries}
          disabled={detectingSeriesState === "pending"}
        >
          {detectingSeriesState === "pending" ? "Detecting…" : "Detect Series in Library"}
        </button>
        {detectingSeriesState && detectingSeriesState !== "pending" && (
          <span className="detect-series-result">
            {detectingSeriesState.error
              ? "Error running detection."
              : detectingSeriesState.updated === 0
              ? "No new series found."
              : `Updated ${detectingSeriesState.updated} book${detectingSeriesState.updated > 1 ? "s" : ""}: ${detectingSeriesState.series_detected.join(", ")}`}
          </span>
        )}
      </div>

      {results && (
        <div className="add-results">
          {results.succeeded.length > 0 && (
            <p className="success">
              {results.succeeded.length} book{results.succeeded.length > 1 ? "s" : ""} added
              successfully.
            </p>
          )}
          {results.failed.length > 0 && (
            <ul className="error-list">
              {results.failed.map((f, i) => (
                <li key={i} className={f.skipped ? "skipped" : "error"}>
                  <strong>{f.name}</strong>: {f.error}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export default AddBook;
