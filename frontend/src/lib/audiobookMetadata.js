const PRODUCT_ID = /\[((?:B[0-9A-Z]{9})|(?:[0-9]{9}[0-9X]))\]/i;

export function audiobookFilenameMetadata(files) {
  const paths = files.map((file) =>
    (file.webkitRelativePath || file.name).replaceAll("\\", "/"),
  );
  const namedFolder = paths
    .flatMap((path) => path.split("/"))
    .find((part) => PRODUCT_ID.test(part));
  const raw = namedFolder || paths[0]?.split("/").at(-1) || "";
  const title = raw
    .replace(/\.(m4b|m4a|mp3|mp4|aac|flac|ogg|opus|wav|cue|zip)$/i, "")
    .replace(PRODUCT_ID, "")
    .trim();
  const series = title.match(
    /^(.+?)[_:]\s*(.+?),\s*(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?)$/i,
  );
  return { title: series?.[1]?.trim() || title, author: "" };
}

export function audiobookCueMetadata(text) {
  const metadata = {};
  for (const line of text.replace(/^\uFEFF/, "").split(/\r?\n/)) {
    if (/^\s*TRACK\s+\d+/i.test(line)) break;
    const match = line.match(/^\s*(TITLE|PERFORMER)\s+"([^"]+)"\s*$/i);
    if (match)
      metadata[match[1].toUpperCase() === "TITLE" ? "title" : "author"] =
        match[2].trim();
  }
  return metadata;
}

export async function suggestAudiobookMetadata(files) {
  const metadata = audiobookFilenameMetadata(files);
  const cue = files.find((file) => /\.cue$/i.test(file.name));
  if (cue) {
    try {
      const text = await cue.slice(0, 256_000).text();
      Object.assign(metadata, audiobookCueMetadata(text));
    } catch {
      // The server retries metadata extraction from the uploaded source.
    }
  }
  return metadata;
}
