import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  previewLibationBackup,
  uploadImportedAudiobook,
} from "../api/audiobook";

const AUDIO_EXTENSIONS = new Set([
  ".aac",
  ".flac",
  ".m4a",
  ".m4b",
  ".mp3",
  ".mp4",
  ".ogg",
  ".opus",
  ".wav",
]);
const IMPORT_EXTENSIONS = new Set([...AUDIO_EXTENSIONS, ".cue", ".zip"]);
const LIBATION_ID_RE = /\[((?:B[0-9A-Z]{9})|(?:[0-9]{9}[0-9X]))\]/i;

function extension(name) {
  const index = name.lastIndexOf(".");
  return index < 0 ? "" : name.slice(index).toLowerCase();
}

function sourcePath(file) {
  return file.webkitRelativePath || file.name;
}

function libationSourceKey(pathValue) {
  const parts = pathValue.replaceAll("\\", "/").split("/").filter(Boolean);
  const folderIndex = parts.findIndex((part) => LIBATION_ID_RE.test(part));
  if (folderIndex < 0) return null;
  let folderName = parts[folderIndex];
  if (folderIndex === parts.length - 1 && extension(folderName) === ".zip") {
    folderName = folderName.slice(0, -4);
  }
  return [...parts.slice(0, folderIndex), folderName].join("/");
}

function filesBySourceKey(files) {
  const groups = new Map();
  files.forEach((file) => {
    if (!IMPORT_EXTENSIONS.has(extension(file.name))) return;
    const key = libationSourceKey(sourcePath(file));
    if (!key) return;
    const group = groups.get(key) || [];
    group.push(file);
    groups.set(key, group);
  });
  groups.forEach((group, key) => {
    if (!group.some((file) => extension(file.name) === ".m4b")) return;
    groups.set(
      key,
      group.filter(
        (file) =>
          !AUDIO_EXTENSIONS.has(extension(file.name)) ||
          extension(file.name) === ".m4b",
      ),
    );
  });
  return groups;
}

function statusLabel(group, existingAudioCount = 0) {
  switch (group.status) {
    case "matched":
      if (existingAudioCount) return "Already has audio — skipped";
      return group.match_method === "identifier"
        ? "Matched by identifier"
        : group.match_method === "title_variant"
          ? "Matched by title variant"
          : "Matched by title";
    case "already_imported":
      return "Exact edition already imported";
    case "ambiguous":
      return "Needs a unique match";
    default:
      return "No library match";
  }
}

function bookOptionLabel(book) {
  if (!book?.book_id) return "";
  const audioLabel = book.existing_audiobooks?.length
    ? " — AUDIO ALREADY ATTACHED"
    : "";
  return `${book.book_title}${book.book_author ? ` — ${book.book_author}` : ""}${audioLabel} (#${book.book_id})`;
}

function audioStatusLabel(status) {
  return (status || "unknown").replaceAll("_", " ");
}

function LibationBackupImport() {
  const queryClient = useQueryClient();
  const inputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [autoAlign, setAutoAlign] = useState(true);
  const [importState, setImportState] = useState(null);
  const [review, setReview] = useState({});
  const [matchFilter, setMatchFilter] = useState("all");

  const inspectFiles = async (selectedFiles) => {
    const selected = Array.from(selectedFiles || []);
    setFiles(selected);
    setPreview(null);
    setPreviewError("");
    setImportState(null);
    if (!selected.length) return;
    setPreviewing(true);
    try {
      const result = await previewLibationBackup(selected.map(sourcePath));
      setPreview(result);
      setReview(
        Object.fromEntries(
          (result.groups || []).map((group) => [
            group.source_key,
            {
              bookId: group.book_id || null,
              included:
                group.status !== "already_imported" &&
                !group.existing_audiobooks?.length,
              input: group.book_id ? bookOptionLabel(group) : "",
            },
          ]),
        ),
      );
      setMatchFilter("all");
    } catch (error) {
      setPreviewError(error.message);
    } finally {
      setPreviewing(false);
    }
  };

  const importMatches = async () => {
    const matches = (preview?.groups || [])
      .filter((group) => {
        const selection = review[group.source_key];
        return selection?.included;
      })
      .map((group) => ({
        ...group,
        book_id: review[group.source_key].bookId,
      }));
    const groupedFiles = filesBySourceKey(files);
    const results = [];
    setImportState({ current: 0, total: matches.length, results, done: false });
    for (const [index, group] of matches.entries()) {
      const groupFiles = groupedFiles.get(group.source_key) || [];
      try {
        if (!groupFiles.length) {
          throw new Error(
            "No supported audio files were found in this folder.",
          );
        }
        await uploadImportedAudiobook(
          group.book_id,
          groupFiles,
          `Libation · ${group.product_id}`,
          group.book_id ? autoAlign : false,
          !group.book_id
            ? { title: group.source_title, inferTitle: true }
            : null,
        );
        results.push({ ...group, result: "queued" });
      } catch (error) {
        results.push({ ...group, result: "failed", error: error.message });
      }
      setImportState({
        current: index + 1,
        total: matches.length,
        results: [...results],
        done: index + 1 === matches.length,
      });
    }
    queryClient.invalidateQueries({ queryKey: ["processing-jobs"] });
    queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
  };

  const reset = () => {
    setFiles([]);
    setPreview(null);
    setPreviewError("");
    setImportState(null);
    setReview({});
    setMatchFilter("all");
    if (inputRef.current) inputRef.current.value = "";
  };

  const updateBookMatch = (group, input) => {
    const option = (preview?.library_books || []).find(
      (book) => bookOptionLabel(book) === input,
    );
    setReview((current) => ({
      ...current,
      [group.source_key]: {
        bookId: option?.book_id || null,
        included: !option?.existing_audiobooks?.length,
        input,
      },
    }));
  };

  const chooseCandidate = (group, candidate) => {
    setReview((current) => ({
      ...current,
      [group.source_key]: {
        bookId: candidate.book_id,
        included: !candidate.existing_audiobooks?.length,
        input: bookOptionLabel(candidate),
      },
    }));
  };

  const queuedCount =
    importState?.results.filter((result) => result.result === "queued")
      .length || 0;
  const failedCount =
    importState?.results.filter((result) => result.result === "failed")
      .length || 0;
  const optionById = new Map(
    (preview?.library_books || []).map((book) => [book.book_id, book]),
  );
  const existingAudioCount = (preview?.groups || []).filter((group) => {
    const selection = review[group.source_key];
    if (!selection?.bookId) return false;
    const selectedBook = optionById.get(selection.bookId);
    return Boolean(
      (selectedBook?.existing_audiobooks ?? group.existing_audiobooks)?.length,
    );
  }).length;
  const selectedCount = (preview?.groups || []).filter((group) => {
    const selection = review[group.source_key];
    return selection?.included;
  }).length;
  const needsReviewCount = (preview?.groups || []).filter((group) => {
    const selection = review[group.source_key];
    return group.status !== "already_imported" && !selection?.included;
  }).length;
  const visibleGroups = (preview?.groups || []).filter((group) => {
    const selection = review[group.source_key];
    const isSelected = Boolean(selection?.included);
    if (matchFilter === "ready") return isSelected;
    if (matchFilter === "review") {
      return group.status !== "already_imported" && !isSelected;
    }
    if (matchFilter === "audio") {
      const selectedBook = optionById.get(selection?.bookId);
      return Boolean(
        (selectedBook?.existing_audiobooks ?? group.existing_audiobooks)
          ?.length,
      );
    }
    return true;
  });

  return (
    <section className="settings-section libation-backup-import">
      <h3>Import a Libation Backup</h3>
      <p className="hint">
        Choose your Libation backup folder. Library matches are attached
        automatically; unmatched books are imported as audio only. You can
        adjust the selection below.
      </p>
      <label className="libation-directory-picker">
        Libation backup directory
        <input
          ref={inputRef}
          type="file"
          multiple
          webkitdirectory=""
          directory=""
          disabled={Boolean(importState && !importState.done)}
          onChange={(event) => inspectFiles(event.target.files)}
        />
      </label>
      {previewing && (
        <p className="hint" role="status">
          Inspecting backup…
        </p>
      )}
      {previewError && <p className="error">{previewError}</p>}

      {preview && (
        <>
          <p className="libation-preview-summary" role="status">
            <strong>{selectedCount} selected to import</strong>
            {` · ${needsReviewCount} need review · ${existingAudioCount} already have human audio`}
            {preview.already_imported_count
              ? ` · ${preview.already_imported_count} exact ${preview.already_imported_count === 1 ? "edition" : "editions"} already imported`
              : ""}
          </p>
          {preview.ignored_file_count > 0 && (
            <p className="hint">
              {preview.ignored_file_count} cover, metadata, duplicate, or
              unsupported{" "}
              {preview.ignored_file_count === 1 ? "file was" : "files were"}{" "}
              ignored.
            </p>
          )}
          <div className="libation-review-toolbar">
            <label>
              Show{" "}
              <select
                value={matchFilter}
                disabled={Boolean(importState)}
                onChange={(event) => setMatchFilter(event.target.value)}
              >
                <option value="all">All {preview.groups.length}</option>
                <option value="review">Needs review {needsReviewCount}</option>
                <option value="ready">Selected {selectedCount}</option>
                <option value="audio">
                  Already has audio {existingAudioCount}
                </option>
              </select>
            </label>
            <span className="hint">
              Title variants include series, volume, and edition suffixes.
            </span>
          </div>
          <datalist id="libation-library-books">
            {(preview.library_books || []).map((book) => (
              <option value={bookOptionLabel(book)} key={book.book_id} />
            ))}
          </datalist>
          <div className="libation-match-list">
            {visibleGroups.map((group) => {
              const selection = review[group.source_key] || {};
              const selectedBook = optionById.get(selection.bookId);
              const canImport = group.status !== "already_imported";
              const existingAudiobooks = selection.bookId
                ? (selectedBook?.existing_audiobooks ??
                  group.existing_audiobooks ??
                  [])
                : [];
              return (
                <div
                  className={`libation-match libation-match--${group.status}${existingAudiobooks.length ? " libation-match--has-audio" : ""}`}
                  key={group.source_key}
                >
                  <div className="libation-match-copy">
                    <div>
                      <strong>{group.source_title}</strong>
                      <span className="hint"> · {group.product_id}</span>
                    </div>
                    {group.detail && !group.book_title && (
                      <p className="hint">{group.detail}</p>
                    )}
                    {existingAudiobooks.length > 0 && (
                      <div className="libation-existing-audio">
                        <strong>
                          {group.status === "already_imported"
                            ? "This exact Libation edition is already attached."
                            : "This library book already has human audio."}
                        </strong>
                        <ul>
                          {existingAudiobooks.map((edition) => (
                            <li key={edition.edition_id}>
                              {edition.name} ·{" "}
                              {audioStatusLabel(edition.status)}
                              {edition.product_id
                                ? ` · ${edition.product_id}`
                                : ""}
                            </li>
                          ))}
                        </ul>
                        <a
                          href={`/books/${selection.bookId}/audiobooks?tab=sources`}
                        >
                          Open existing audio
                        </a>
                      </div>
                    )}
                    {canImport && (
                      <label className="libation-book-search">
                        Library match
                        <input
                          type="text"
                          list="libation-library-books"
                          value={selection.input || ""}
                          placeholder="Type a title or author…"
                          disabled={Boolean(importState)}
                          aria-label={`Library match for ${group.source_title}`}
                          onChange={(event) =>
                            updateBookMatch(group, event.target.value)
                          }
                        />
                      </label>
                    )}
                    {!selection.bookId && group.candidates?.length > 0 && (
                      <div className="libation-suggestions">
                        <span className="hint">Possible matches:</span>
                        {group.candidates.map((candidate) => (
                          <button
                            type="button"
                            className="btn-text"
                            key={candidate.book_id}
                            disabled={Boolean(importState)}
                            onClick={() => chooseCandidate(group, candidate)}
                          >
                            {candidate.book_title}
                            {candidate.book_author
                              ? ` by ${candidate.book_author}`
                              : ""}
                          </button>
                        ))}
                      </div>
                    )}
                    {canImport && (
                      <label className="libation-include-match">
                        <input
                          type="checkbox"
                          checked={Boolean(selection.included)}
                          disabled={Boolean(importState)}
                          onChange={(event) =>
                            setReview((current) => ({
                              ...current,
                              [group.source_key]: {
                                ...current[group.source_key],
                                included: event.target.checked,
                              },
                            }))
                          }
                        />{" "}
                        {existingAudiobooks.length
                          ? "Import another audio edition anyway"
                          : "Include this audiobook in the import"}
                      </label>
                    )}
                  </div>
                  <span className="libation-match-status">
                    {!selection.bookId && canImport
                      ? "Audio only"
                      : selection.bookId &&
                          group.status !== "matched" &&
                          group.status !== "already_imported"
                        ? "Match reviewed"
                        : statusLabel(group, existingAudiobooks.length)}
                  </span>
                </div>
              );
            })}
          </div>
          <label>
            <input
              type="checkbox"
              checked={autoAlign}
              disabled={Boolean(importState)}
              onChange={(event) => setAutoAlign(event.target.checked)}
            />{" "}
            Run configured speech-to-text alignment after matching (WhisperX
            recommended)
          </label>
          <div className="settings-actions">
            <button
              type="button"
              className="btn-primary"
              disabled={
                selectedCount === 0 || Boolean(importState) || previewing
              }
              onClick={importMatches}
            >
              Import {selectedCount} Selected{" "}
              {selectedCount === 1 ? "Book" : "Books"}
            </button>
            <button
              type="button"
              className="btn-text"
              disabled={Boolean(importState && !importState.done)}
              onClick={reset}
            >
              Choose Another Backup
            </button>
          </div>
        </>
      )}

      {importState && (
        <div className="libation-import-progress" role="status">
          <p>
            {importState.done
              ? `Queued ${queuedCount} of ${importState.total} books${failedCount ? `; ${failedCount} failed to upload` : ""}.`
              : `Uploading book ${Math.min(importState.current + 1, importState.total)} of ${importState.total}. Keep this page open until all uploads are queued.`}
          </p>
          <progress value={importState.current} max={importState.total} />
          {importState.results
            .filter((result) => result.result === "failed")
            .map((result) => (
              <p className="error" key={result.source_key}>
                {result.source_title}: {result.error}
              </p>
            ))}
        </div>
      )}
      <p className="hint">
        Unmatched books are selected as audio only automatically. Uncheck any
        books you want to skip. Already imported editions are skipped.
      </p>
    </section>
  );
}

export default LibationBackupImport;
