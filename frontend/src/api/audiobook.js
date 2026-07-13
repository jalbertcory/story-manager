import { getJson, sendJson, sendWithoutBody } from "./client";

// Pipeline control
export function getAudiobookStatus(bookId) {
  return getJson(`/api/books/${bookId}/audiobook/status`, "Failed to fetch audiobook status");
}

export function startPipeline(bookId) {
  return sendWithoutBody(`/api/books/${bookId}/audiobook/start`, {
    method: "POST",
    fallbackMessage: "Failed to start pipeline",
  });
}

export function pausePipeline(bookId) {
  return sendWithoutBody(`/api/books/${bookId}/audiobook/pause`, {
    method: "POST",
    fallbackMessage: "Failed to pause pipeline",
  });
}

export function rebuildPipeline(bookId) {
  return sendWithoutBody(`/api/books/${bookId}/audiobook/rebuild`, {
    method: "POST",
    fallbackMessage: "Failed to rebuild pipeline",
  });
}

// Characters
export function getCharacters(bookId) {
  return getJson(`/api/books/${bookId}/audiobook/characters`, "Failed to fetch characters");
}

export function updateCharacter(charId, data) {
  return sendJson(`/api/audiobook/characters/${charId}`, {
    method: "PUT",
    body: data,
    fallbackMessage: "Failed to update character",
  });
}

// Sentences
export function getSentences(bookId, { page = 1, limit = 50, chapterId } = {}) {
  const params = new URLSearchParams({ page, limit });
  if (chapterId != null) params.set("chapter_id", chapterId);
  return getJson(`/api/books/${bookId}/audiobook/sentences?${params}`, "Failed to fetch sentences");
}

export function updateSentence(sentenceId, data) {
  return sendJson(`/api/audiobook/sentences/${sentenceId}`, {
    method: "PUT",
    body: data,
    fallbackMessage: "Failed to update sentence",
  });
}

export function getSentenceAudioUrl(sentenceId) {
  return `/api/audiobook/sentences/${sentenceId}/audio`;
}

// Chapters
export function getAudiobookChapters(bookId) {
  return getJson(`/api/books/${bookId}/audiobook/chapters`, "Failed to fetch chapters");
}

export function getChapterAudioUrl(bookId, chapterId) {
  return `/api/books/${bookId}/audiobook/chapters/${chapterId}/audio`;
}

export function getAudiobookDownloadUrl(bookId) {
  return `/api/books/${bookId}/audiobook/download`;
}

// Settings
export function getAudiobookSettings() {
  return getJson("/api/audiobook/settings", "Failed to fetch audiobook settings");
}

export function updateAudiobookSettings(data) {
  return sendJson("/api/audiobook/settings", {
    method: "PUT",
    body: data,
    fallbackMessage: "Failed to save audiobook settings",
  });
}
