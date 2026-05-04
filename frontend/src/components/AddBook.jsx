import { forwardRef, useImperativeHandle, useRef, useState } from "react";
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

const extractEpubsFromEntries = async (entries) => {
  const readDir = (dirEntry) =>
    new Promise((resolve) => {
      const reader = dirEntry.createReader();
      const all = [];
      const batch = () => {
        reader.readEntries(async (batchEntries) => {
          if (!batchEntries.length) {
            resolve(all);
            return;
          }
          for (const entry of batchEntries) {
            if (entry.isFile) {
              if (entry.name.toLowerCase().endsWith(".epub")) {
                all.push(await new Promise((r) => entry.file(r)));
              }
            } else if (entry.isDirectory) {
              all.push(...(await readDir(entry)));
            }
          }
          batch();
        });
      };
      batch();
    });

  const files = [];
  for (const entry of entries) {
    if (entry.isDirectory) {
      files.push(...(await readDir(entry)));
    } else if (entry.isFile) {
      const lower = entry.name.toLowerCase();
      if (lower.endsWith(".epub") || lower.endsWith(".zip")) {
        files.push(await new Promise((r) => entry.file(r)));
      }
    }
  }
  return files;
};

const AddBook = forwardRef(function AddBook(_props, ref) {
  const queryClient = useQueryClient();
  const [files, setFiles] = useState([]);
  const [urls, setUrls] = useState([""]);
  const [dragging, setDragging] = useState(false);
  const [pending, setPending] = useState(false);
  const [results, setResults] = useState(null);
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);

  useImperativeHandle(ref, () => ({
    addFilesFromEntries: async (entries) => {
      const newFiles = await extractEpubsFromEntries(entries);
      if (newFiles.length > 0) setFiles((prev) => [...prev, ...newFiles]);
    },
  }));

  const handleFileChange = (e) => {
    setFiles((prev) => [...prev, ...Array.from(e.target.files)]);
    e.target.value = "";
  };

  const handleFolderChange = (e) => {
    const epubs = Array.from(e.target.files).filter((f) =>
      f.name.toLowerCase().endsWith(".epub")
    );
    setFiles((prev) => [...prev, ...epubs]);
    e.target.value = "";
  };

  const removeFile = (index) => setFiles((prev) => prev.filter((_, i) => i !== index));

  const handleUrlChange = (index, value) =>
    setUrls((prev) => prev.map((u, i) => (i === index ? value : u)));

  const addUrlField = () => setUrls((prev) => [...prev, ""]);

  const removeUrlField = (index) => setUrls((prev) => prev.filter((_, i) => i !== index));

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
  };

  const handleDrop = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    const entries = Array.from(e.dataTransfer.items)
      .map((item) => item.webkitGetAsEntry?.())
      .filter(Boolean);
    const newFiles = await extractEpubsFromEntries(entries);
    setFiles((prev) => [...prev, ...newFiles]);
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

    queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
    setFiles([]);
    setUrls([""]);
    setPending(false);
    setResults({ succeeded, skipped, failed, totalProcessed: succeeded.length + skipped.length + failed.length });
  };

  const total = files.length + urls.filter((u) => u.trim()).length;

  return (
    <div className="add-book-container">
      <form onSubmit={handleSubmit}>
        <div className="add-book-columns">
          <div
            id="drop-zone"
            className={`drop-zone ${dragging ? "dragging" : ""} ${files.length > 0 ? "drop-zone--has-files" : ""}`}
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
                <li className="add-more-hint">+ more files</li>
              </ul>
            ) : (
              <div className="drop-zone-empty">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="28" height="28">
                  <path d="M12 16V6m0 0l-4 4m4-4l4 4" strokeLinecap="round" strokeLinejoin="round"/>
                  <path d="M20 16.7V19a2 2 0 01-2 2H6a2 2 0 01-2-2v-2.3" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                <span>Drop EPUBs, ZIPs, or folders here</span>
                <div className="drop-zone-browse">
                  <button
                    type="button"
                    className="browse-link"
                    onClick={(e) => { e.stopPropagation(); fileInputRef.current.click(); }}
                  >
                    Browse files
                  </button>
                  <span className="browse-sep">·</span>
                  <button
                    type="button"
                    className="browse-link"
                    onClick={(e) => { e.stopPropagation(); folderInputRef.current.click(); }}
                  >
                    Browse folder
                  </button>
                </div>
              </div>
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
            <input
              type="file"
              accept=".epub"
              multiple
              webkitdirectory=""
              onChange={handleFolderChange}
              ref={folderInputRef}
              style={{ display: "none" }}
            />
          </div>

          <div className="add-book-divider">
            <span>or</span>
          </div>

          <div className="url-section">
            {urls.map((url, i) => (
              <div key={i} className="url-row">
                <input
                  type="text"
                  placeholder="Paste a web novel URL"
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
              + Add another URL
            </button>
          </div>
        </div>

        <button className="btn-primary add-book-submit" type="submit" disabled={pending || total === 0}>
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
});

export default AddBook;
