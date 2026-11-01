import { stringValue } from "../../lib/errors";
import type { Book } from "../../types";
import type { components } from "../../api/schema";
import type { previewCleaning } from "../../api/cleaning";
import { useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

type EditableValues = ReturnType<typeof editableValues>;
type EditableKey = keyof EditableValues;
type BookUpdate = components["schemas"]["BookUpdate"];

// The server-backed fields the form edits, in their form representation.
function editableValues(book: Book) {
  return {
    title: book.title || "",
    author: book.author || "",
    series: book.series || "",
    seriesIndex: book.series_index != null ? String(book.series_index) : "",
    notes: book.notes || "",
    isbn10: stringValue(book.metadata_remote_ids?.isbn_10),
    isbn13: stringValue(book.metadata_remote_ids?.isbn_13),
    asin: stringValue(book.metadata_remote_ids?.asin),
    googleBooksVolumeId: stringValue(
      book.metadata_remote_ids?.google_books_volume_id,
    ),
    openLibraryWorkKey: stringValue(
      book.metadata_remote_ids?.open_library_work_key,
    ),
    openLibraryEditionKey: stringValue(
      book.metadata_remote_ids?.open_library_edition_key,
    ),
    openLibraryAuthorKey: stringValue(
      book.metadata_remote_ids?.open_library_author_key,
    ),
    otherRemoteIdsJson: splitRemoteIds(book.metadata_remote_ids).extrasJson,
    userGenreTags: (book.user_genre_tags || []).join(", "),
    removedChapters: book.removed_chapters || [],
    contentSelectors: book.content_selectors || [],
  };
}

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

const REMOTE_ID_KEYS = [
  "isbn10",
  "isbn13",
  "asin",
  "googleBooksVolumeId",
  "openLibraryWorkKey",
  "openLibraryEditionKey",
  "openLibraryAuthorKey",
  "otherRemoteIdsJson",
] as const satisfies readonly EditableKey[];

const EDITABLE_KEYS = [
  "title",
  "author",
  "series",
  "seriesIndex",
  "notes",
  ...REMOTE_ID_KEYS,
  "userGenreTags",
  "removedChapters",
  "contentSelectors",
] as const satisfies readonly EditableKey[];

function remoteIdsUpdate(
  values: EditableValues,
): { ids: Record<string, unknown> | null } | { error: string } {
  let extraRemoteIds: Record<string, unknown> = {};
  if (values.otherRemoteIdsJson.trim()) {
    try {
      const parsed: unknown = JSON.parse(values.otherRemoteIdsJson);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        return { error: "Other identifiers must be a JSON object." };
      extraRemoteIds = Object.fromEntries(Object.entries(parsed));
    } catch {
      return { error: "Other identifiers must be valid JSON." };
    }
  }
  const named = {
    isbn_10: values.isbn10,
    isbn_13: values.isbn13,
    asin: values.asin,
    google_books_volume_id: values.googleBooksVolumeId,
    open_library_work_key: values.openLibraryWorkKey,
    open_library_edition_key: values.openLibraryEditionKey,
    open_library_author_key: values.openLibraryAuthorKey,
  };
  const ids = { ...extraRemoteIds };
  for (const [key, value] of Object.entries(named))
    if (value.trim()) ids[key] = value.trim();
  return { ids: Object.keys(ids).length ? ids : null };
}

// The update for the fields the user changed since the form was seeded, so a
// save never overwrites values the server changed meanwhile (a metadata
// recheck, another tab) with the stale copies the form loaded.
export function changedBookFields(
  values: EditableValues,
  seeded: EditableValues,
): { update: BookUpdate } | { error: string } {
  const changed = (key: EditableKey) => !sameValue(values[key], seeded[key]);
  let remoteIds: BookUpdate = {};
  if (REMOTE_ID_KEYS.some(changed)) {
    const result = remoteIdsUpdate(values);
    if ("error" in result) return result;
    remoteIds = { metadata_remote_ids: result.ids };
  }
  return {
    update: {
      ...(changed("title") ? { title: values.title } : {}),
      ...(changed("author") ? { author: values.author } : {}),
      ...(changed("series") ? { series: values.series.trim() || null } : {}),
      ...(changed("seriesIndex")
        ? {
            series_index: values.seriesIndex.trim()
              ? Number.parseFloat(values.seriesIndex)
              : null,
          }
        : {}),
      ...(changed("userGenreTags")
        ? {
            user_genre_tags: values.userGenreTags
              .split(",")
              .map((tag) => tag.trim())
              .filter(Boolean),
          }
        : {}),
      ...remoteIds,
      ...(changed("removedChapters")
        ? { removed_chapters: values.removedChapters }
        : {}),
      ...(changed("contentSelectors")
        ? { content_selectors: values.contentSelectors }
        : {}),
      ...(changed("notes") ? { notes: values.notes || null } : {}),
    },
  };
}

import { splitRemoteIds } from "./remoteIds";

export function useBookSettingsForm(initialBook: Book) {
  const [title, setTitle] = useState(initialBook.title || "");
  const [author, setAuthor] = useState(initialBook.author || "");
  const [series, setSeries] = useState(initialBook.series || "");
  const [seriesIndex, setSeriesIndex] = useState(
    initialBook.series_index != null ? String(initialBook.series_index) : "",
  );
  const [notes, setNotes] = useState(initialBook.notes || "");
  const [isbn10, setIsbn10] = useState(
    stringValue(initialBook.metadata_remote_ids?.isbn_10),
  );
  const [isbn13, setIsbn13] = useState(
    stringValue(initialBook.metadata_remote_ids?.isbn_13),
  );
  const [asin, setAsin] = useState(
    stringValue(initialBook.metadata_remote_ids?.asin),
  );
  const [googleBooksVolumeId, setGoogleBooksVolumeId] = useState(
    stringValue(initialBook.metadata_remote_ids?.google_books_volume_id),
  );
  const [openLibraryWorkKey, setOpenLibraryWorkKey] = useState(
    stringValue(initialBook.metadata_remote_ids?.open_library_work_key),
  );
  const [openLibraryEditionKey, setOpenLibraryEditionKey] = useState(
    stringValue(initialBook.metadata_remote_ids?.open_library_edition_key),
  );
  const [openLibraryAuthorKey, setOpenLibraryAuthorKey] = useState(
    stringValue(initialBook.metadata_remote_ids?.open_library_author_key),
  );
  const [otherRemoteIdsJson, setOtherRemoteIdsJson] = useState(
    splitRemoteIds(initialBook.metadata_remote_ids).extrasJson,
  );
  const [identifierError, setIdentifierError] = useState("");
  const [userGenreTags, setUserGenreTags] = useState(
    (initialBook.user_genre_tags || []).join(", "),
  );
  const [removedChapters, setRemovedChapters] = useState(
    initialBook.removed_chapters || [],
  );
  const [contentSelectors, setContentSelectors] = useState(
    initialBook.content_selectors || [],
  );
  const [previewResult, setPreviewResult] = useState<Awaited<
    ReturnType<typeof previewCleaning>
  > | null>(null);
  const [chapterSearch, setChapterSearch] = useState("");
  const [chaptersExpanded, setChaptersExpanded] = useState(false);
  const [chapterPreviewMode, setChapterPreviewMode] = useState("original");
  const [identifiersExpanded, setIdentifiersExpanded] = useState(false);

  const currentValues: EditableValues = {
    title,
    author,
    series,
    seriesIndex,
    notes,
    isbn10,
    isbn13,
    asin,
    googleBooksVolumeId,
    openLibraryWorkKey,
    openLibraryEditionKey,
    openLibraryAuthorKey,
    otherRemoteIdsJson,
    userGenreTags,
    removedChapters,
    contentSelectors,
  };
  // The book the form was last synchronized with. Background refetches (refresh
  // polling, cover changes) replace the book object; they must not discard
  // edits the user has not saved yet.
  const [seededBook, setSeededBook] = useState(initialBook);
  const seededValues = editableValues(seededBook);
  const isDirty = !sameValue(currentValues, seededValues);
  const setters: {
    [K in EditableKey]: Dispatch<SetStateAction<EditableValues[K]>>;
  } = {
    title: setTitle,
    author: setAuthor,
    series: setSeries,
    seriesIndex: setSeriesIndex,
    notes: setNotes,
    isbn10: setIsbn10,
    isbn13: setIsbn13,
    asin: setAsin,
    googleBooksVolumeId: setGoogleBooksVolumeId,
    openLibraryWorkKey: setOpenLibraryWorkKey,
    openLibraryEditionKey: setOpenLibraryEditionKey,
    openLibraryAuthorKey: setOpenLibraryAuthorKey,
    otherRemoteIdsJson: setOtherRemoteIdsJson,
    userGenreTags: setUserGenreTags,
    removedChapters: setRemovedChapters,
    contentSelectors: setContentSelectors,
  };

  if (initialBook !== seededBook) {
    const differentBook = initialBook.id !== seededBook.id;
    const next = editableValues(initialBook);
    setSeededBook(initialBook);
    // Fields the user has not edited follow the server; edited fields keep the
    // user's value until they save or leave.
    const rebase = <K extends EditableKey>(key: K) => {
      if (differentBook || sameValue(currentValues[key], seededValues[key]))
        setters[key](next[key]);
    };
    EDITABLE_KEYS.forEach(rebase);
    if (differentBook) {
      setIdentifierError("");
      setPreviewResult(null);
      setChapterSearch("");
      setChaptersExpanded(false);
      setChapterPreviewMode("original");
      setIdentifiersExpanded(false);
    }
  }

  useEffect(() => {
    setPreviewResult(null);
  }, [contentSelectors, removedChapters]);

  const getUpdatedFields = (): BookUpdate | null => {
    const result = changedBookFields(currentValues, seededValues);
    if ("error" in result) {
      setIdentifierError(result.error);
      return null;
    }
    setIdentifierError("");
    return result.update;
  };

  return {
    title,
    setTitle,
    author,
    setAuthor,
    series,
    setSeries,
    seriesIndex,
    setSeriesIndex,
    notes,
    setNotes,
    isbn10,
    setIsbn10,
    isbn13,
    setIsbn13,
    asin,
    setAsin,
    googleBooksVolumeId,
    setGoogleBooksVolumeId,
    openLibraryWorkKey,
    setOpenLibraryWorkKey,
    openLibraryEditionKey,
    setOpenLibraryEditionKey,
    openLibraryAuthorKey,
    setOpenLibraryAuthorKey,
    otherRemoteIdsJson,
    setOtherRemoteIdsJson,
    identifierError,
    userGenreTags,
    setUserGenreTags,
    removedChapters,
    setRemovedChapters,
    contentSelectors,
    setContentSelectors,
    previewResult,
    setPreviewResult,
    chapterSearch,
    setChapterSearch,
    chaptersExpanded,
    setChaptersExpanded,
    chapterPreviewMode,
    setChapterPreviewMode,
    identifiersExpanded,
    setIdentifiersExpanded,
    getUpdatedFields,
    isDirty,
  };
}
