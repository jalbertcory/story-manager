import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { getAllBookCatalog } from "../api/books";
import { uploadImportedAudiobook } from "../api/audiobook";
import {
  addWebNovel,
  previewBookImports,
  uploadEpubs,
} from "../api/imports";
import LibationBackupImport from "./LibationBackupImport.jsx";

const IMPORT_TYPES = [
  {
    key: "books",
    label: "Book files",
    description: "EPUB files, ZIP archives, or folders",
  },
  {
    key: "web",
    label: "Web novels",
    description: "One or more source URLs",
  },
  {
    key: "audiobook",
    label: "Audiobook",
    description: "Human narration for a library book",
  },
  {
    key: "libation",
    label: "Libation backup",
    description: "Match and queue an entire backup",
  },
];

const AUDIO_EXTENSIONS = new Set([
  ".aac",
  ".cue",
  ".flac",
  ".m4a",
  ".m4b",
  ".mp3",
  ".mp4",
  ".ogg",
  ".opus",
  ".wav",
  ".zip",
]);

const MATCH_STOP_WORDS = new Set([
  "and",
  "book",
  "edition",
  "series",
  "the",
  "volume",
]);

function requestedImportType() {
  const requested = new URLSearchParams(window.location.search).get("type");
  return IMPORT_TYPES.some((item) => item.key === requested)
    ? requested
    : "books";
}

function requestedBookId() {
  const value = Number.parseInt(
    new URLSearchParams(window.location.search).get("book_id"),
    10,
  );
  return Number.isInteger(value) ? value : null;
}

const readDirEntries = (reader) =>
  new Promise((resolve, reject) => reader.readEntries(resolve, reject));

const getFileFromEntry = (fileEntry) =>
  new Promise((resolve, reject) => fileEntry.file(resolve, reject));

async function extractEpubsFromEntries(entries) {
  const readDir = async (dirEntry) => {
    const reader = dirEntry.createReader();
    const files = [];
    let batch;
    do {
      batch = await readDirEntries(reader);
      for (const entry of batch) {
        if (entry.isFile && entry.name.toLowerCase().endsWith(".epub")) {
          try {
            files.push(await getFileFromEntry(entry));
          } catch {
            // Unreadable files are reported by omission in the selection summary.
          }
        } else if (entry.isDirectory) {
          files.push(...(await readDir(entry)));
        }
      }
    } while (batch.length > 0);
    return files;
  };

  const files = [];
  for (const entry of entries) {
    if (entry.isDirectory) {
      try {
        files.push(...(await readDir(entry)));
      } catch {
        // Ignore unreadable directories.
      }
    } else if (entry.isFile) {
      const lower = entry.name.toLowerCase();
      if (lower.endsWith(".epub") || lower.endsWith(".zip")) {
        try {
          files.push(await getFileFromEntry(entry));
        } catch {
          // Ignore unreadable files.
        }
      }
    }
  }
  return files;
}

function extension(name) {
  const index = name.lastIndexOf(".");
  return index < 0 ? "" : name.slice(index).toLowerCase();
}

function selectAudiobookFiles(selectedFiles) {
  const supported = Array.from(selectedFiles || []).filter((file) =>
    AUDIO_EXTENSIONS.has(extension(file.name)),
  );
  const hasM4b = supported.some((file) => extension(file.name) === ".m4b");
  if (!hasM4b) return supported;
  return supported.filter(
    (file) =>
      ![
        ".aac",
        ".flac",
        ".m4a",
        ".mp3",
        ".mp4",
        ".ogg",
        ".opus",
        ".wav",
      ].includes(extension(file.name)) || extension(file.name) === ".m4b",
  );
}

function normalizeMatchText(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function bookLabel(book) {
  return `${book.title} — ${book.author || "Unknown author"}`;
}

function titleVariants(title) {
  const full = normalizeMatchText(title);
  const titleText = String(title || "");
  const primary = normalizeMatchText(
    titleText.split(":", 1)[0].split("(", 1)[0].split("[", 1)[0],
  );
  return [...new Set([full, primary].filter(Boolean))];
}

function significantTokens(value) {
  return normalizeMatchText(value)
    .split(" ")
    .filter((token) => token.length > 2 && !MATCH_STOP_WORDS.has(token));
}

function scoreFilenameMatch(book, fileText) {
  const normalizedFile = normalizeMatchText(fileText);
  const variants = titleVariants(book.title);
  let score = 0;

  variants.forEach((variant, index) => {
    if (variant.length >= 4 && normalizedFile.includes(variant)) {
      score = Math.max(score, (index === 0 ? 1000 : 900) + variant.length);
    }
  });

  const titleTokens = significantTokens(book.title);
  const fileTokens = new Set(significantTokens(fileText));
  const matchedTokens = titleTokens.filter((token) => fileTokens.has(token));
  const coverage = titleTokens.length
    ? matchedTokens.length / titleTokens.length
    : 0;
  if (matchedTokens.length >= 2 && coverage >= 0.7) {
    score = Math.max(score, 500 + coverage * 100 + matchedTokens.length);
  }

  if (score > 0) {
    const authorTokens = significantTokens(book.author);
    score += authorTokens.filter((token) => fileTokens.has(token)).length * 10;
  }
  return score;
}

function findFilenameBookMatch(files, catalog) {
  const fileText = files
    .map((file) => file.webkitRelativePath || file.name)
    .join(" ");
  const candidates = catalog
    .map((book) => ({ book, score: scoreFilenameMatch(book, fileText) }))
    .filter((candidate) => candidate.score > 0)
    .sort((left, right) => right.score - left.score);

  if (!candidates.length) return null;
  if (candidates[1] && candidates[0].score - candidates[1].score < 5) {
    return null;
  }
  return candidates[0].book;
}

function scoreBookSearch(book, normalizedQuery) {
  const title = normalizeMatchText(book.title);
  const author = normalizeMatchText(book.author);
  if (title === normalizedQuery) return 100;
  if (title.startsWith(normalizedQuery)) return 90;
  if (title.includes(normalizedQuery)) return 80;
  if (author === normalizedQuery) return 70;
  if (author.startsWith(normalizedQuery)) return 60;
  if (author.includes(normalizedQuery)) return 50;
  return 0;
}

function previewStatusLabel(status) {
  switch (status) {
    case "ready":
      return "Ready";
    case "duplicate":
      return "Duplicate — will skip";
    case "unsupported":
      return "Unsupported";
    default:
      return "Needs correction";
  }
}

function resultLabel(status) {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

const AddBook = forwardRef(function AddBook(
  { initialEntries = [], onEntriesConsumed },
  ref,
) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef(null);
  const audioInputRef = useRef(null);
  const audioDirectoryRef = useRef(null);
  const lastAutoMatchSignatureRef = useRef("");
  const [importType, setImportType] = useState(requestedImportType);
  const [files, setFiles] = useState([]);
  const [urls, setUrls] = useState([""]);
  const [audioFiles, setAudioFiles] = useState([]);
  const [selectedBookId, setSelectedBookId] = useState(requestedBookId);
  const [audioMatchNotice, setAudioMatchNotice] = useState("");
  const [editionName, setEditionName] = useState("");
  const [autoAlign, setAutoAlign] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [duplicatesReviewed, setDuplicatesReviewed] = useState(false);
  const [importing, setImporting] = useState(false);
  const [results, setResults] = useState(null);

  const { data: catalog = [] } = useQuery({
    queryKey: ["import-book-catalog"],
    queryFn: () =>
      getAllBookCatalog({ q: "", sortBy: "title", sortOrder: "asc" }),
    enabled: importType === "audiobook",
    staleTime: 30_000,
  });

  const addEntryFiles = async (entries) => {
    const newFiles = await extractEpubsFromEntries(entries);
    if (newFiles.length) {
      setImportType("books");
      setFiles((current) => [...current, ...newFiles]);
      setPreview(null);
      setResults(null);
    }
  };

  useImperativeHandle(ref, () => ({ addFilesFromEntries: addEntryFiles }));

  useEffect(() => {
    if (!initialEntries.length) return;
    void addEntryFiles(initialEntries).finally(() => onEntriesConsumed?.());
    // The parent clears the consumed entries; this effect should only rerun for
    // a genuinely new browser drop, not because a callback identity changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialEntries]);

  useEffect(() => {
    const onPopState = () => {
      setImportType(requestedImportType());
      setSelectedBookId(requestedBookId());
      setAudioMatchNotice("");
      setPreview(null);
      setResults(null);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    const signature = audioFiles
      .map((file) => file.webkitRelativePath || file.name)
      .join("|");
    if (
      !signature ||
      !catalog.length ||
      selectedBookId ||
      lastAutoMatchSignatureRef.current === signature
    ) {
      return;
    }

    lastAutoMatchSignatureRef.current = signature;
    const matchedBook = findFilenameBookMatch(audioFiles, catalog);
    if (matchedBook) {
      setSelectedBookId(matchedBook.id);
      setAudioMatchNotice(
        `Matched from the filename: ${bookLabel(matchedBook)}. Please confirm before importing.`,
      );
    }
  }, [audioFiles, catalog, selectedBookId]);

  const resetInspection = () => {
    setPreview(null);
    setPreviewError("");
    setDuplicatesReviewed(false);
    setResults(null);
  };

  const chooseAudioFiles = (selectedFiles) => {
    lastAutoMatchSignatureRef.current = "";
    setAudioMatchNotice("");
    setAudioFiles(selectAudiobookFiles(selectedFiles));
    resetInspection();
  };

  const chooseType = (type) => {
    if (type === importType) return;
    const params = new URLSearchParams();
    params.set("type", type);
    window.history.pushState(
      { view: "tab", tab: "import" },
      "",
      `/import?${params}`,
    );
    setImportType(type);
    resetInspection();
  };

  const handleDrop = async (event) => {
    event.preventDefault();
    event.stopPropagation();
    setDragging(false);
    const entries = Array.from(event.dataTransfer.items)
      .map((item) => item.webkitGetAsEntry?.())
      .filter(Boolean);
    if (entries.length) {
      await addEntryFiles(entries);
      return;
    }
    const selected = Array.from(event.dataTransfer.files).filter((file) =>
      file.name.toLowerCase().endsWith(".epub") ||
      file.name.toLowerCase().endsWith(".zip"),
    );
    setFiles((current) => [...current, ...selected]);
    resetInspection();
  };

  const inspect = async () => {
    setPreviewing(true);
    setPreviewError("");
    setResults(null);
    setDuplicatesReviewed(false);
    try {
      if (importType === "books") {
        setPreview(await previewBookImports(files, []));
      } else if (importType === "web") {
        setPreview(
          await previewBookImports(
            [],
            urls.map((url) => url.trim()).filter(Boolean),
          ),
        );
      } else if (importType === "audiobook") {
        const book = catalog.find((item) => item.id === selectedBookId);
        if (!book || !audioFiles.length) {
          throw new Error("Choose a library book and at least one supported audio file.");
        }
        setPreview({
          ready_count: 1,
          duplicate_count: 0,
          unsupported_count: 0,
          error_count: 0,
          items: [
            {
              key: "audiobook:0",
              input_type: "audiobook",
              name: editionName.trim() || audioFiles[0].name,
              status: "ready",
              title: book.title,
              author: book.author,
              detail: `${audioFiles.length} supported ${audioFiles.length === 1 ? "file" : "files"} will be attached to this book.`,
            },
          ],
        });
      }
    } catch (error) {
      setPreviewError(error.message);
    } finally {
      setPreviewing(false);
    }
  };

  const execute = async () => {
    setImporting(true);
    const completed = [];
    try {
      if (importType === "books") {
        try {
          const response = await uploadEpubs(files);
          response.forEach((item) => {
            completed.push({
              name: item.book?.title || item.filename,
              status:
                item.status === "success"
                  ? "succeeded"
                  : item.status === "skipped"
                    ? "skipped"
                    : "failed",
              detail: item.error,
            });
          });
        } catch (error) {
          files.forEach((file) =>
            completed.push({
              name: file.name,
              status: "failed",
              detail: error.message,
            }),
          );
        }
      } else if (importType === "web") {
        for (const item of preview.items.filter((entry) => entry.status === "ready")) {
          try {
            const book = await addWebNovel(item.source_url);
            completed.push({
              name: book.title || item.source_url,
              status: "queued",
              detail: "The durable web import will continue in Activity.",
            });
          } catch (error) {
            completed.push({
              name: item.source_url,
              status: "failed",
              detail: error.message,
            });
          }
        }
      } else if (importType === "audiobook") {
        try {
          const edition = await uploadImportedAudiobook(
            selectedBookId,
            audioFiles,
            editionName,
            autoAlign,
          );
          completed.push({
            name: edition.name || editionName || audioFiles[0].name,
            status: "queued",
            detail: "Import and chapter matching will continue in Activity.",
          });
        } catch (error) {
          completed.push({
            name: editionName || audioFiles[0].name,
            status: "failed",
            detail: error.message,
          });
        }
      }

      if (importType === "web") {
        preview.items
          .filter((item) => item.status !== "ready")
          .forEach((item) =>
            completed.push({
              name: item.title || item.source_url || item.name,
              status: item.status === "duplicate" ? "skipped" : "failed",
              detail: item.detail,
            }),
          );
      }
      setResults(completed);
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["active-processing-jobs"] });
      queryClient.invalidateQueries({ queryKey: ["attention-dashboard"] });
    } finally {
      setImporting(false);
    }
  };

  const activeUrls = urls.map((url) => url.trim()).filter(Boolean);
  const canInspect =
    (importType === "books" && files.length > 0) ||
    (importType === "web" && activeUrls.length > 0) ||
    (importType === "audiobook" && selectedBookId && audioFiles.length > 0);
  const stage = results ? 3 : preview ? 2 : 1;
  const canImport =
    (preview?.ready_count > 0 || preview?.duplicate_count > 0) &&
    (preview.duplicate_count === 0 || duplicatesReviewed);
  const selectionHeading = {
    books: "Select book files",
    web: "Enter source URLs",
    audiobook: "Match narration to a library book",
  }[importType];

  if (importType === "libation") {
    return (
      <div className="import-workflow">
        <ImportHeader stage={1} />
        <ImportTypePicker selected={importType} onSelect={chooseType} />
        <LibationBackupImport />
      </div>
    );
  }

  return (
    <div className="import-workflow">
      <ImportHeader stage={stage} />
      <ImportTypePicker selected={importType} onSelect={chooseType} />

      {!preview && !results && (
        <section className="import-panel" aria-labelledby="import-input-heading">
          <span className="import-step-code">01 / SELECT</span>
          <h3 id="import-input-heading">{selectionHeading}</h3>

          {importType === "books" && (
            <>
              <div
                id="drop-zone"
                className={`drop-zone import-drop-zone${dragging ? " dragging" : ""}`}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
              >
                <strong>Drop EPUBs, ZIPs, or folders here</strong>
                <span>or click to browse for files</span>
                <input
                  id="file-upload"
                  ref={fileInputRef}
                  type="file"
                  accept=".epub,.zip"
                  multiple
                  hidden
                  onChange={(event) => {
                    setFiles((current) => [
                      ...current,
                      ...Array.from(event.target.files),
                    ]);
                    resetInspection();
                    event.target.value = "";
                  }}
                />
              </div>
              <SelectedFiles files={files} onRemove={(index) => {
                setFiles((current) => current.filter((_, itemIndex) => itemIndex !== index));
                resetInspection();
              }} />
            </>
          )}

          {importType === "web" && (
            <div className="import-url-list">
              {urls.map((url, index) => (
                <label key={index}>
                  Web novel URL {urls.length > 1 ? index + 1 : ""}
                  <span className="import-url-row">
                    <input
                      type="url"
                      placeholder="https://example.com/story/..."
                      value={url}
                      onChange={(event) => {
                        setUrls((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index ? event.target.value : item,
                          ),
                        );
                        resetInspection();
                      }}
                    />
                    {urls.length > 1 && (
                      <button
                        type="button"
                        className="btn-text"
                        onClick={() =>
                          setUrls((current) => {
                            resetInspection();
                            return current.filter(
                              (_, itemIndex) => itemIndex !== index,
                            );
                          })
                        }
                      >
                        Remove
                      </button>
                    )}
                  </span>
                </label>
              ))}
              <button
                type="button"
                className="btn-text"
                onClick={() => setUrls((current) => [...current, ""])}
              >
                + Add another URL
              </button>
            </div>
          )}

          {importType === "audiobook" && (
            <div className="import-audiobook-inputs">
              <BookCombobox
                books={catalog}
                selectedBookId={selectedBookId}
                onSelect={(bookId) => {
                  lastAutoMatchSignatureRef.current = audioFiles
                    .map((file) => file.webkitRelativePath || file.name)
                    .join("|");
                  setSelectedBookId(bookId);
                  setAudioMatchNotice("");
                  resetInspection();
                }}
              />
              {audioMatchNotice && (
                <p className="import-match-notice" role="status">
                  {audioMatchNotice}
                </p>
              )}
              <label>
                Edition name (optional)
                <input
                  value={editionName}
                  onChange={(event) => setEditionName(event.target.value)}
                  placeholder="For example, Audible / Jeff Hays"
                />
              </label>
              <div className="import-audio-pickers">
                <label>
                  Audiobook files or ZIP
                  <input
                    ref={audioInputRef}
                    type="file"
                    multiple
                    accept=".zip,.cue,.m4b,.m4a,.mp3,.mp4,.aac,.flac,.ogg,.opus,.wav,audio/*"
                    onChange={(event) => chooseAudioFiles(event.target.files)}
                  />
                </label>
                <label>
                  Or audiobook directory
                  <input
                    ref={audioDirectoryRef}
                    type="file"
                    multiple
                    webkitdirectory=""
                    directory=""
                    onChange={(event) => chooseAudioFiles(event.target.files)}
                  />
                </label>
              </div>
              <SelectedFiles files={audioFiles} />
              <label className="import-checkbox">
                <input
                  type="checkbox"
                  checked={autoAlign}
                  onChange={(event) => setAutoAlign(event.target.checked)}
                />
                Improve sentence timestamps with configured speech-to-text alignment
              </label>
            </div>
          )}

          <div className="import-actions">
            <button
              type="button"
              className="btn-primary"
              disabled={!canInspect || previewing}
              onClick={inspect}
            >
              {previewing ? "Inspecting…" : "Inspect selection"}
            </button>
          </div>
          {previewError && <p className="error">{previewError}</p>}
        </section>
      )}

      {preview && !results && (
        <section className="import-panel" aria-labelledby="import-preview-heading">
          <span className="import-step-code">02 / REVIEW</span>
          <h3 id="import-preview-heading">Review before importing</h3>
          <p className="import-preview-summary" role="status">
            <strong>{preview.ready_count} ready</strong>
            {` · ${preview.duplicate_count} duplicate · ${preview.unsupported_count} unsupported · ${preview.error_count} with errors`}
          </p>
          <div className="import-preview-list">
            {preview.items.map((item) => (
              <article
                key={item.key}
                className={`import-preview-item import-preview-item--${item.status}`}
              >
                <div>
                  <strong>{item.title || item.source_url || item.name}</strong>
                  {item.author && <span>{item.author}</span>}
                  {item.series && <small>Series: {item.series}</small>}
                  {item.cleaning_configs?.length > 0 && (
                    <small>
                      Cleaning: {item.cleaning_configs.join(", ")}
                    </small>
                  )}
                  {item.detail && <small>{item.detail}</small>}
                </div>
                <span className="import-preview-status">
                  {previewStatusLabel(item.status)}
                </span>
              </article>
            ))}
          </div>
          {preview.duplicate_count > 0 && (
            <label className="import-checkbox import-duplicate-confirmation">
              <input
                type="checkbox"
                checked={duplicatesReviewed}
                onChange={(event) => setDuplicatesReviewed(event.target.checked)}
              />
              I reviewed the duplicates and want to skip them.
            </label>
          )}
          <div className="import-actions">
            <button
              type="button"
              className="btn-primary"
              disabled={!canImport || importing}
              onClick={execute}
            >
              {importing
                ? "Starting import…"
                : preview.ready_count > 0
                  ? `Import ${preview.ready_count} ready`
                  : preview.duplicate_count > 0
                    ? `Finish with ${preview.duplicate_count} skipped`
                    : "Nothing ready to import"}
            </button>
            <button type="button" className="btn-text" onClick={resetInspection}>
              Change selection
            </button>
          </div>
        </section>
      )}

      {results && (
        <section className="import-panel" aria-labelledby="import-results-heading">
          <span className="import-step-code">03 / RESULTS</span>
          <h3 id="import-results-heading">Import results</h3>
          <div className="import-result-list" role="status">
            {results.map((item, index) => (
              <div className={`import-result import-result--${item.status}`} key={`${item.name}-${index}`}>
                <strong>{item.name}</strong>
                <span>{resultLabel(item.status)}</span>
                {item.detail && <small>{item.detail}</small>}
              </div>
            ))}
          </div>
          <div className="import-actions">
            <button
              type="button"
              className="btn-primary"
              onClick={() => {
                setFiles([]);
                setAudioFiles([]);
                setUrls([""]);
                setPreview(null);
                setResults(null);
              }}
            >
              Import more
            </button>
            <a className="btn" href="/activity/processing">
              View Activity
            </a>
          </div>
        </section>
      )}
    </div>
  );
});

function ImportHeader({ stage }) {
  return (
    <header className="import-workflow-header">
      <span className="attention-eyebrow">GUIDED WORKFLOW</span>
      <h2>Add to library</h2>
      <p>Inspect inputs, resolve conflicts, and then start durable import work.</p>
      <ol className="import-steps" aria-label="Import progress">
        {["Select", "Review", "Results"].map((label, index) => (
          <li
            key={label}
            className={stage >= index + 1 ? "import-steps--active" : ""}
            aria-current={stage === index + 1 ? "step" : undefined}
          >
            <span>{index + 1}</span>
            {label}
          </li>
        ))}
      </ol>
    </header>
  );
}

function ImportTypePicker({ selected, onSelect }) {
  return (
    <div className="import-type-picker" role="group" aria-label="Import source type">
      {IMPORT_TYPES.map((item) => (
        <button
          key={item.key}
          type="button"
          className={selected === item.key ? "import-type--active" : ""}
          aria-pressed={selected === item.key}
          onClick={() => onSelect(item.key)}
        >
          <strong>{item.label}</strong>
          <span>{item.description}</span>
        </button>
      ))}
    </div>
  );
}

function BookCombobox({ books, selectedBookId, onSelect }) {
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

  const chooseBook = (book) => {
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
              className={index === activeIndex ? "import-book-option--active" : ""}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => chooseBook(book)}
            >
              <strong>{book.title}</strong>
              <span>{book.author || "Unknown author"}</span>
            </li>
          ))}
          {!options.length && <li className="import-book-options-empty">No matching books</li>}
        </ul>
      )}
    </div>
  );
}

function SelectedFiles({ files, onRemove }) {
  if (!files.length) return null;
  return (
    <ul className="import-selected-files">
      {files.map((file, index) => (
        <li key={`${file.name}-${index}`}>
          <span>{file.webkitRelativePath || file.name}</span>
          {onRemove && (
            <button
              type="button"
              className="btn-text"
              aria-label={`Remove ${file.name}`}
              onClick={() => onRemove(index)}
            >
              Remove
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

export default AddBook;
