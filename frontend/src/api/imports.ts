import { api, unwrap, multipart } from "./client";

export function previewBookImports(files: File[] = [], urls: string[] = []) {
  return unwrap(
    api.POST("/api/imports/preview", {
      body: { files, urls },
      bodySerializer: multipart,
    }),
    "Failed to inspect import inputs",
  );
}
export function uploadEpubs(files: File[]) {
  return unwrap(
    api.POST("/api/books/upload_epubs", {
      body: { files },
      bodySerializer: multipart,
    }),
    "File upload failed",
  );
}
export function addWebNovel(url: string) {
  return unwrap(
    api.POST("/api/books/add_web_novel", { body: { url } }),
    "Failed to add web novel",
  );
}
export function detectSeries() {
  return unwrap(
    api.POST("/api/books/detect-series"),
    "Failed to detect series",
  );
}
