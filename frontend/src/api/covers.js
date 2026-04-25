import { sendForm, sendJson, sendWithoutBody } from "./client";

export function uploadBookCover(bookId, file) {
  const form = new FormData();
  form.append("file", file);
  return sendForm(`/api/books/${bookId}/cover`, form, {
    fallbackMessage: "Cover upload failed",
  });
}

export function retryBookCover(bookId) {
  return sendWithoutBody(`/api/books/${bookId}/retry-cover`, {
    fallbackMessage: "Failed to retry cover",
  });
}

export function setBookCoverUrl(bookId, url) {
  return sendJson(`/api/books/${bookId}/cover-url`, {
    body: { url },
    fallbackMessage: "Failed to set cover from URL",
  });
}

export function getApiCoverUrl(bookId) {
  return `/api/covers/${bookId}`;
}
