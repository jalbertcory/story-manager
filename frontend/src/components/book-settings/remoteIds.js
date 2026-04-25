const COMMON_REMOTE_ID_KEYS = [
  "isbn_10",
  "isbn_13",
  "google_books_volume_id",
  "open_library_work_key",
  "open_library_edition_key",
  "open_library_author_key",
];

export function splitRemoteIds(remoteIds) {
  const source = remoteIds && typeof remoteIds === "object" ? remoteIds : {};
  const common = {};
  COMMON_REMOTE_ID_KEYS.forEach((key) => {
    common[key] = source[key] || "";
  });

  const extras = Object.fromEntries(
    Object.entries(source).filter(
      ([key]) => !COMMON_REMOTE_ID_KEYS.includes(key),
    ),
  );

  return {
    common,
    extrasJson: Object.keys(extras).length
      ? JSON.stringify(extras, null, 2)
      : "",
  };
}
