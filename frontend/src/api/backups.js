import { getJson, sendWithoutBody } from "./client";

export function getBackups() {
  return getJson("/api/backups", "Failed to load backups");
}

export function createBackup() {
  return sendWithoutBody("/api/backups", {
    fallbackMessage: "Failed to queue backup",
  });
}

export function verifyBackup(filename) {
  return sendWithoutBody(
    `/api/backups/${encodeURIComponent(filename)}/verify`,
    {
      fallbackMessage: "Failed to queue backup verification",
    },
  );
}

export function deleteBackup(filename) {
  return sendWithoutBody(`/api/backups/${encodeURIComponent(filename)}`, {
    method: "DELETE",
    fallbackMessage: "Failed to delete backup",
  });
}
