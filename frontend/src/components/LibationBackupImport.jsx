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

function statusLabel(group) {
  switch (group.status) {
    case "matched":
      return group.match_method === "identifier"
        ? "Matched by identifier"
        : "Matched by title";
    case "already_imported":
      return "Already imported";
    case "ambiguous":
      return "Needs a unique match";
    default:
      return "No library match";
  }
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
    } catch (error) {
      setPreviewError(error.message);
    } finally {
      setPreviewing(false);
    }
  };

  const importMatches = async () => {
    const matches = (preview?.groups || []).filter(
      (group) => group.status === "matched",
    );
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
          autoAlign,
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
    if (inputRef.current) inputRef.current.value = "";
  };

  const queuedCount =
    importState?.results.filter((result) => result.result === "queued")
      .length || 0;
  const failedCount =
    importState?.results.filter((result) => result.result === "failed")
      .length || 0;

  return (
    <section className="settings-section libation-backup-import">
      <h3>Import a Libation Backup</h3>
      <p className="hint">
        Choose the directory that contains all of your Libation book folders.
        Story Manager previews identifier and exact-title matches before any
        audio is transferred, skips books that are not in this library, and
        queues each matched book separately.
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
            <strong>{preview.matched_count} ready to import</strong>
            {` · ${preview.already_imported_count} already imported · ${preview.unmatched_count} unmatched`}
            {preview.ambiguous_count
              ? ` · ${preview.ambiguous_count} ambiguous`
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
          <div className="libation-match-list">
            {preview.groups.map((group) => (
              <div
                className={`libation-match libation-match--${group.status}`}
                key={group.source_key}
              >
                <div>
                  <strong>{group.source_title}</strong>
                  <span className="hint"> · {group.product_id}</span>
                  {group.book_title && (
                    <p className="hint">
                      Library: {group.book_title}
                      {group.book_author ? ` by ${group.book_author}` : ""}
                    </p>
                  )}
                  {!group.book_title && group.detail && (
                    <p className="hint">{group.detail}</p>
                  )}
                </div>
                <span className="libation-match-status">
                  {statusLabel(group)}
                </span>
              </div>
            ))}
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
                preview.matched_count === 0 ||
                Boolean(importState) ||
                previewing
              }
              onClick={importMatches}
            >
              Import {preview.matched_count} Matched{" "}
              {preview.matched_count === 1 ? "Book" : "Books"}
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
              ? `Queued ${queuedCount} of ${importState.total} matched books${failedCount ? `; ${failedCount} failed to upload` : ""}.`
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
        Unmatched books are not uploaded. Add their EPUBs to Story Manager and
        select this backup again later; already imported books will be skipped.
      </p>
    </section>
  );
}

export default LibationBackupImport;
