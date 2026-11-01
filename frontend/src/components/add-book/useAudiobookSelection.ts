import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getAllBookCatalog } from "../../api/books";
import { uploadImportedAudiobook } from "../../api/audiobook";
import { suggestAudiobookMetadata } from "../../lib/audiobookMetadata";
import { errorMessage } from "../../lib/errors";
import { bookLabel, findFilenameBookMatch } from "../../lib/filenameMatching";
import { selectAudiobookFiles } from "../../lib/importFiles";
import { queryKeys } from "../../lib/queryKeys";
import type { CatalogBook } from "../../types";
import type { ImportResult } from "./importTypes";

const NO_BOOKS: CatalogBook[] = [];

const fileSignature = (files: File[]) =>
  files.map((file) => file.webkitRelativePath || file.name).join("|");

// What the audiobook import form has picked: the files, the library book they
// narrate (matched from filenames unless the user chose one), and the details
// for a new audio-only book. `onChange` runs whenever the selection changes.
export function useAudiobookSelection({
  enabled,
  initialBookId,
  onChange,
}: {
  enabled: boolean;
  initialBookId: number | null;
  onChange: () => void;
}) {
  const lastAutoMatchSignature = useRef("");
  const manualBookSelection = useRef(Boolean(initialBookId));
  const titleEdited = useRef(false);
  const authorEdited = useRef(false);
  const selectionVersion = useRef(0);
  const [files, setFiles] = useState<File[]>([]);
  const [readingMetadata, setReadingMetadata] = useState(false);
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [selectedBookId, setSelectedBookId] = useState(initialBookId);
  const [matchNotice, setMatchNotice] = useState("");
  const [editionName, setEditionName] = useState("");
  const [autoAlign, setAutoAlign] = useState(true);

  const catalogQuery = useQuery({
    queryKey: queryKeys.importBookCatalog,
    queryFn: ({ signal }) =>
      getAllBookCatalog(
        { q: "", sortBy: "title", sortOrder: "asc" },
        { signal },
      ),
    enabled,
    staleTime: 30_000,
  });
  const catalog = catalogQuery.data ?? NO_BOOKS;

  const createsBook = !selectedBookId;
  const selectedBook = catalog.find((book) => book.id === selectedBookId);
  const audioOnly = createsBook || selectedBook?.source_type === "audiobook";

  useEffect(() => {
    const signature = fileSignature(files);
    if (
      !signature ||
      !catalog.length ||
      selectedBookId ||
      lastAutoMatchSignature.current === signature
    ) {
      return;
    }

    lastAutoMatchSignature.current = signature;
    const matchedBook = findFilenameBookMatch(files, catalog);
    if (matchedBook) {
      setSelectedBookId(matchedBook.id);
      setMatchNotice(`Matched from the filename: ${bookLabel(matchedBook)}.`);
    }
  }, [files, catalog, selectedBookId]);

  const chooseFiles = async (selectedFiles: FileList | File[] | null) => {
    lastAutoMatchSignature.current = "";
    if (!manualBookSelection.current) setSelectedBookId(null);
    setMatchNotice("");
    const selected = selectAudiobookFiles(selectedFiles);
    setFiles(selected);
    const version = ++selectionVersion.current;
    onChange();
    setReadingMetadata(true);
    const suggested = await suggestAudiobookMetadata(selected);
    if (version !== selectionVersion.current) return;
    setReadingMetadata(false);
    if (!titleEdited.current) setTitle(suggested.title || "");
    if (!authorEdited.current) setAuthor(suggested.author || "");
  };

  const editTitle = (value: string) => {
    titleEdited.current = Boolean(value.trim());
    setTitle(value);
    onChange();
  };

  const editAuthor = (value: string) => {
    authorEdited.current = Boolean(value.trim());
    setAuthor(value);
    onChange();
  };

  const selectBook = (bookId: number | null) => {
    lastAutoMatchSignature.current = fileSignature(files);
    manualBookSelection.current = Boolean(bookId);
    setSelectedBookId(bookId);
    setMatchNotice("");
    onChange();
  };

  // The address bar asked for a specific book (Back/Forward or a link).
  const requestBook = (bookId: number | null) => {
    if (bookId == null) return;
    manualBookSelection.current = true;
    setSelectedBookId(bookId);
    setMatchNotice("");
  };

  const reset = () => {
    setFiles([]);
    setSelectedBookId(null);
    manualBookSelection.current = false;
    titleEdited.current = false;
    authorEdited.current = false;
    setTitle("");
    setAuthor("");
    setEditionName("");
    setMatchNotice("");
  };

  const upload = async (): Promise<ImportResult> => {
    try {
      const edition = await uploadImportedAudiobook(
        selectedBookId,
        files,
        editionName,
        audioOnly ? false : autoAlign,
        createsBook
          ? {
              title: title.trim(),
              author: authorEdited.current ? author.trim() : "",
              inferTitle: !titleEdited.current,
            }
          : null,
      );
      return {
        name: edition.name || editionName || files[0]?.name || "Audiobook",
        status: "queued",
        detail: "Import and chapter matching will continue in Activity.",
      };
    } catch (error) {
      return {
        name: editionName || files[0]?.name || "Audiobook",
        status: "failed",
        detail: errorMessage(error),
      };
    }
  };

  return {
    files,
    fileSignature: fileSignature(files),
    catalog,
    catalogLoading: catalogQuery.isPending,
    catalogFailed: catalogQuery.isError,
    reloadCatalog: catalogQuery.refetch,
    readingMetadata,
    title,
    author,
    selectedBookId,
    matchNotice,
    editionName,
    autoAlign,
    createsBook,
    audioOnly,
    ready:
      !catalogQuery.isPending &&
      !catalogQuery.isError &&
      !readingMetadata &&
      files.length > 0,
    chooseFiles,
    editTitle,
    editAuthor,
    selectBook,
    requestBook,
    setEditionName,
    setAutoAlign,
    reset,
    upload,
  };
}

export type AudiobookSelection = ReturnType<typeof useAudiobookSelection>;
