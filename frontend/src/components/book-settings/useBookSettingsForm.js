import { useEffect, useState } from "react";

import { splitRemoteIds } from "./remoteIds";

export function useBookSettingsForm(initialBook) {
  const [title, setTitle] = useState(initialBook.title || "");
  const [author, setAuthor] = useState(initialBook.author || "");
  const [series, setSeries] = useState(initialBook.series || "");
  const [seriesIndex, setSeriesIndex] = useState(
    initialBook.series_index != null ? String(initialBook.series_index) : "",
  );
  const [notes, setNotes] = useState(initialBook.notes || "");
  const [isbn10, setIsbn10] = useState(
    initialBook.metadata_remote_ids?.isbn_10 || "",
  );
  const [isbn13, setIsbn13] = useState(
    initialBook.metadata_remote_ids?.isbn_13 || "",
  );
  const [googleBooksVolumeId, setGoogleBooksVolumeId] = useState(
    initialBook.metadata_remote_ids?.google_books_volume_id || "",
  );
  const [openLibraryWorkKey, setOpenLibraryWorkKey] = useState(
    initialBook.metadata_remote_ids?.open_library_work_key || "",
  );
  const [openLibraryEditionKey, setOpenLibraryEditionKey] = useState(
    initialBook.metadata_remote_ids?.open_library_edition_key || "",
  );
  const [openLibraryAuthorKey, setOpenLibraryAuthorKey] = useState(
    initialBook.metadata_remote_ids?.open_library_author_key || "",
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
  const [previewResult, setPreviewResult] = useState(null);
  const [chapterSearch, setChapterSearch] = useState("");
  const [chaptersExpanded, setChaptersExpanded] = useState(false);
  const [chapterPreviewMode, setChapterPreviewMode] = useState("original");
  const [identifiersExpanded, setIdentifiersExpanded] = useState(false);

  useEffect(() => {
    setTitle(initialBook.title || "");
    setAuthor(initialBook.author || "");
    setSeries(initialBook.series || "");
    setSeriesIndex(
      initialBook.series_index != null ? String(initialBook.series_index) : "",
    );
    setNotes(initialBook.notes || "");
    setIsbn10(initialBook.metadata_remote_ids?.isbn_10 || "");
    setIsbn13(initialBook.metadata_remote_ids?.isbn_13 || "");
    setGoogleBooksVolumeId(
      initialBook.metadata_remote_ids?.google_books_volume_id || "",
    );
    setOpenLibraryWorkKey(
      initialBook.metadata_remote_ids?.open_library_work_key || "",
    );
    setOpenLibraryEditionKey(
      initialBook.metadata_remote_ids?.open_library_edition_key || "",
    );
    setOpenLibraryAuthorKey(
      initialBook.metadata_remote_ids?.open_library_author_key || "",
    );
    setOtherRemoteIdsJson(
      splitRemoteIds(initialBook.metadata_remote_ids).extrasJson,
    );
    setIdentifierError("");
    setUserGenreTags((initialBook.user_genre_tags || []).join(", "));
    setRemovedChapters(initialBook.removed_chapters || []);
    setContentSelectors(initialBook.content_selectors || []);
    setPreviewResult(null);
    setChapterSearch("");
    setChaptersExpanded(false);
    setChapterPreviewMode("original");
    setIdentifiersExpanded(false);
  }, [initialBook]);

  useEffect(() => {
    setPreviewResult(null);
  }, [contentSelectors, removedChapters]);

  const getUpdatedFields = () => {
    let extraRemoteIds = {};
    if (otherRemoteIdsJson.trim()) {
      try {
        const parsed = JSON.parse(otherRemoteIdsJson);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          setIdentifierError("Other identifiers must be a JSON object.");
          return null;
        }
        extraRemoteIds = parsed;
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
  };
}
