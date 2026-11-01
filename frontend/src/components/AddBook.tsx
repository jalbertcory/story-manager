import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { addWebNovel, previewBookImports, uploadEpubs } from "../api/imports";
import { errorMessage } from "../lib/errors";
import { extractEpubsFromEntries } from "../lib/importFiles";
import { invalidateBookViews, queryKeys } from "../lib/queryKeys";
import { useLocation, useNavigate } from "../lib/router";
import LibationBackupImport from "./LibationBackupImport";
import AudiobookInput from "./add-book/AudiobookInput";
import BookFilesInput from "./add-book/BookFilesInput";
import { ImportHeader, ImportTypePicker } from "./add-book/ImportLayout";
import { ImportResults, ImportReview } from "./add-book/ImportReview";
import type { ImportPreview } from "./add-book/ImportReview";
import { IMPORT_TYPES } from "./add-book/importTypes";
import type { ImportResult } from "./add-book/importTypes";
import { useAudiobookSelection } from "./add-book/useAudiobookSelection";
import WebUrlsInput from "./add-book/WebUrlsInput";

const SELECTION_HEADINGS: Record<string, string> = {
  books: "Select book files",
  web: "Enter source URLs",
  audiobook: "Import an audiobook",
};

function requestedImportType(search: string) {
  const requested = new URLSearchParams(search).get("type") || "books";
  return IMPORT_TYPES.some((item) => item.key === requested)
    ? requested
    : "books";
}

function requestedBookId(search: string) {
  const value = Number.parseInt(
    new URLSearchParams(search).get("book_id") || "",
    10,
  );
  return Number.isInteger(value) ? value : null;
}

async function importBookFiles(files: File[]): Promise<ImportResult[]> {
  try {
    const response = await uploadEpubs(files);
    return response.map((item) => ({
      name: item.book?.title || item.filename,
      status:
        item.status === "success"
          ? "succeeded"
          : item.status === "skipped"
            ? "skipped"
            : "failed",
      detail: item.error,
    }));
  } catch (error) {
    return files.map((file) => ({
      name: file.name,
      status: "failed",
      detail: errorMessage(error),
    }));
  }
}

// Starts a download for each ready URL; the rest are reported as skipped or
// failed from the preview.
async function importWebNovels(
  preview: ImportPreview | null,
): Promise<ImportResult[]> {
  const items = preview?.items || [];
  const completed: ImportResult[] = [];
  for (const item of items.filter((entry) => entry.status === "ready")) {
    try {
      const book = await addWebNovel(item.source_url || "");
      completed.push({
        name: book.title || item.source_url || item.name,
        status: "queued",
        detail: "Download started. Follow its progress in Background activity.",
      });
    } catch (error) {
      completed.push({
        name: item.source_url || item.name,
        status: "failed",
        detail: errorMessage(error),
      });
    }
  }
  for (const item of items.filter((entry) => entry.status !== "ready")) {
    completed.push({
      name: item.title || item.source_url || item.name,
      status: item.status === "duplicate" ? "skipped" : "failed",
      detail: item.detail,
    });
  }
  return completed;
}

export default function AddBook({
  initialEntries = [],
  onEntriesConsumed,
}: {
  initialEntries?: FileSystemEntry[];
  onEntriesConsumed?: () => void;
}) {
  const queryClient = useQueryClient();
  const { search } = useLocation();
  const navigate = useNavigate();
  const [importType, setImportType] = useState(() =>
    requestedImportType(search),
  );
  const [files, setFiles] = useState<File[]>([]);
  const [urls, setUrls] = useState([""]);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [duplicatesReviewed, setDuplicatesReviewed] = useState(false);
  const [importing, setImporting] = useState(false);
  const [results, setResults] = useState<ImportResult[] | null>(null);

  const resetInspection = () => {
    setPreview(null);
    setPreviewError("");
    setDuplicatesReviewed(false);
    setResults(null);
  };

  const audio = useAudiobookSelection({
    enabled: importType === "audiobook",
    initialBookId: requestedBookId(search),
    onChange: resetInspection,
  });

  const addFiles = (newFiles: File[]) => {
    setFiles((current) => [...current, ...newFiles]);
    resetInspection();
  };

  const addEntryFiles = async (entries: FileSystemEntry[]) => {
    let newFiles: File[];
    try {
      newFiles = await extractEpubsFromEntries(entries);
    } catch (error) {
      setPreviewError(errorMessage(error));
      return;
    }
    if (newFiles.length) {
      setImportType("books");
      setFiles((current) => [...current, ...newFiles]);
      setPreview(null);
      setResults(null);
    }
  };

  // StrictMode runs effects twice on mount; remember the drop already taken
  // so its files are not appended twice.
  const consumedEntries = useRef<typeof initialEntries | null>(null);
  useEffect(() => {
    if (!initialEntries.length || consumedEntries.current === initialEntries)
      return;
    consumedEntries.current = initialEntries;
    void addEntryFiles(initialEntries).finally(() => onEntriesConsumed?.());
    // The parent clears the consumed entries; this effect should only rerun for
    // a genuinely new browser drop, not because a callback identity changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialEntries]);

  // Follow the address bar when it changes (Back/Forward, a link, or a drop
  // anywhere in the app); what the user already picked is kept.
  const seenSearch = useRef(search);
  useEffect(() => {
    if (seenSearch.current === search) return;
    seenSearch.current = search;
    setImportType(requestedImportType(search));
    audio.requestBook(requestedBookId(search));
    setPreview(null);
    setResults(null);
    // `audio` is a new object each render; only a new location matters here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const chooseType = (type: string) => {
    if (type === importType) return;
    setImportType(type);
    resetInspection();
    navigate(`/import?${new URLSearchParams({ type })}`);
  };

  const inspect = async () => {
    setPreviewing(true);
    setPreviewError("");
    setResults(null);
    setDuplicatesReviewed(false);
    try {
      setPreview(
        importType === "books"
          ? await previewBookImports(files, [])
          : await previewBookImports(
              [],
              urls.map((url) => url.trim()).filter(Boolean),
            ),
      );
    } catch (error) {
      setPreviewError(errorMessage(error));
    } finally {
      setPreviewing(false);
    }
  };

  const execute = async () => {
    setImporting(true);
    try {
      setResults(
        importType === "books"
          ? await importBookFiles(files)
          : importType === "web"
            ? await importWebNovels(preview)
            : [await audio.upload()],
      );
      invalidateBookViews(queryClient);
      for (const queryKey of [
        queryKeys.importBookCatalog,
        queryKeys.activeProcessingJobs,
        queryKeys.attentionDashboard,
      ])
        void queryClient.invalidateQueries({ queryKey });
    } finally {
      setImporting(false);
    }
  };

  const importMore = () => {
    setFiles([]);
    audio.reset();
    setUrls([""]);
    setPreview(null);
    setResults(null);
  };

  const canInspect =
    (importType === "books" && files.length > 0) ||
    (importType === "web" && urls.some((url) => url.trim())) ||
    (importType === "audiobook" && audio.ready);
  const directImport = importType === "audiobook";
  const stage = results ? (directImport ? 2 : 3) : preview ? 2 : 1;

  if (importType === "libation") {
    return (
      <div className="import-workflow">
        <ImportHeader stage={1} />
        <ImportTypePicker
          selected={importType}
          onSelect={chooseType}
          disabled={importing}
        />
        <LibationBackupImport />
      </div>
    );
  }

  return (
    <div className="import-workflow">
      <ImportHeader stage={stage} directImport={directImport} />
      <ImportTypePicker
        selected={importType}
        onSelect={chooseType}
        disabled={importing}
      />

      {!preview && !results && (
        <section
          className="import-panel"
          aria-labelledby="import-input-heading"
        >
          <span className="import-step-code">01 / SELECT</span>
          <h3 id="import-input-heading">{SELECTION_HEADINGS[importType]}</h3>

          {importType === "books" && (
            <BookFilesInput
              files={files}
              onAddFiles={addFiles}
              onAddEntries={addEntryFiles}
              onRemove={(index) => {
                setFiles((current) =>
                  current.filter((_, itemIndex) => itemIndex !== index),
                );
                resetInspection();
              }}
            />
          )}

          {importType === "web" && (
            <WebUrlsInput
              urls={urls}
              onChange={(next) => {
                setUrls(next);
                resetInspection();
              }}
            />
          )}

          {importType === "audiobook" && (
            <AudiobookInput audio={audio} disabled={importing} />
          )}

          <div className="import-actions">
            <button
              type="button"
              className="btn-primary"
              disabled={!canInspect || previewing || importing}
              onClick={() => {
                void (directImport ? execute() : inspect());
              }}
            >
              {directImport
                ? importing
                  ? "Importing…"
                  : "Import audiobook"
                : previewing
                  ? "Inspecting…"
                  : "Inspect selection"}
            </button>
          </div>
          {previewError && (
            <p className="error" role="alert">
              {previewError}
            </p>
          )}
        </section>
      )}

      {preview && !results && (
        <ImportReview
          preview={preview}
          duplicatesReviewed={duplicatesReviewed}
          onDuplicatesReviewed={setDuplicatesReviewed}
          importing={importing}
          onImport={() => {
            void execute();
          }}
          onChangeSelection={resetInspection}
        />
      )}

      {results && (
        <ImportResults
          results={results}
          directImport={directImport}
          onImportMore={importMore}
        />
      )}
    </div>
  );
}
