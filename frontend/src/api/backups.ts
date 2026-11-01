import { api, unwrap, unwrapEmpty, requestInit } from "./client";
import type { RequestOptions } from "./client";

export function getBackups(options?: RequestOptions) {
  return unwrap(
    api.GET("/api/backups", requestInit(options)),
    "Failed to load backups",
  );
}

export function createBackup() {
  return unwrap(api.POST("/api/backups"), "Failed to queue backup");
}

export function verifyBackup(filename: string) {
  return unwrap(
    api.POST("/api/backups/{filename}/verify", {
      params: { path: { filename: filename } },
    }),
    "Failed to queue backup verification",
  );
}

export function deleteBackup(filename: string) {
  return unwrapEmpty(
    api.DELETE("/api/backups/{filename}", {
      params: { path: { filename: filename } },
    }),
    "Failed to delete backup",
  );
}
