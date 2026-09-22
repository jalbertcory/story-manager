import { stringValue } from "../../lib/errors";
import type { Book } from "../../types";
import type { components } from "../../api/schema";
import type { previewCleaning } from "../../api/cleaning";
import { useEffect, useState } from "react";

type EditableValues = ReturnType<typeof editableValues>;

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

function sameValues(left: EditableValues, right: EditableValues): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
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
  const isDirty = !sameValues(currentValues, editableValues(seededBook));

  if (initialBook !== seededBook) {
    const differentBook = initialBook.id !== seededBook.id;
    setSeededBook(initialBook);
    if (differentBook || !isDirty) {
      const next = editableValues(initialBook);
      setTitle(next.title);
      setAuthor(next.author);
      setSeries(next.series);
      setSeriesIndex(next.seriesIndex);
      setNotes(next.notes);
      setIsbn10(next.isbn10);
      setIsbn13(next.isbn13);
      setAsin(next.asin);
      setGoogleBooksVolumeId(next.googleBooksVolumeId);
      setOpenLibraryWorkKey(next.openLibraryWorkKey);
      setOpenLibraryEditionKey(next.openLibraryEditionKey);
      setOpenLibraryAuthorKey(next.openLibraryAuthorKey);
      setOtherRemoteIdsJson(next.otherRemoteIdsJson);
      setUserGenreTags(next.userGenreTags);
      setRemovedChapters(next.removedChapters);
      setContentSelectors(next.contentSelectors);
    }
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

  const getUpdatedFields = (): components["schemas"]["BookUpdate"] | null => {
    let extraRemoteIds: Record<string, unknown> = {};
    if (otherRemoteIdsJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(otherRemoteIdsJson);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          setIdentifierError("Other identifiers must be a JSON object.");
          return null;
        }
        extraRemoteIds = Object.fromEntries(Object.entries(parsed));
      } catch {
        setIdentifierError("Other identifiers must be valid JSON.");
        return null;
      }
    }

    setIdentifierError("");

    const metadataRemoteIds = {
      ...extraRemoteIds,
      ...(isbn10.trim() ? { isbn_10: isbn10.trim() } : {}),
      ...(isbn13.trim() ? { isbn_13: isbn13.trim() } : {}),
      ...(asin.trim() ? { asin: asin.trim() } : {}),
      ...(googleBooksVolumeId.trim()
        ? { google_books_volume_id: googleBooksVolumeId.trim() }
        : {}),
      ...(openLibraryWorkKey.trim()
        ? { open_library_work_key: openLibraryWorkKey.trim() }
        : {}),
      ...(openLibraryEditionKey.trim()
        ? { open_library_edition_key: openLibraryEditionKey.trim() }
        : {}),
      ...(openLibraryAuthorKey.trim()
        ? { open_library_author_key: openLibraryAuthorKey.trim() }
        : {}),
    };

    return {
      title,
      author,
      series: series.trim() || null,
      series_index: seriesIndex.trim() ? Number.parseFloat(seriesIndex) : null,
      user_genre_tags: userGenreTags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
      metadata_remote_ids: Object.keys(metadataRemoteIds).length
        ? metadataRemoteIds
        : null,
      removed_chapters: removedChapters,
      content_selectors: contentSelectors,
      notes: notes || null,
    };
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
