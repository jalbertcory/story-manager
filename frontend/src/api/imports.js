import { sendForm, sendJson } from "./client";

export function previewBookImports(files = [], urls = []) {
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  urls.forEach((url) => body.append("urls", url));
  return sendForm("/api/imports/preview", body, {
    fallbackMessage: "Failed to inspect import inputs",
  });
}

export function uploadEpubs(files) {
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  return sendForm("/api/books/upload_epubs", body, {
    fallbackMessage: "File upload failed",
  });
}

export function addWebNovel(url) {
  return sendJson("/api/books/add_web_novel", {
    body: { url },
    fallbackMessage: "Failed to add web novel",
  });
}
