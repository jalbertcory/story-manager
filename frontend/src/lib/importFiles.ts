// Picks the files an import can use out of a browser selection or drop.

const AUDIO_EXTENSIONS = new Set([
  ".aac",
  ".cue",
  ".flac",
  ".m4a",
  ".m4b",
  ".mp3",
  ".mp4",
  ".ogg",
  ".opus",
  ".wav",
  ".zip",
]);

// Loose audio tracks that an .m4b in the same selection already contains.
const TRACK_EXTENSIONS = new Set([
  ".aac",
  ".flac",
  ".m4a",
  ".mp3",
  ".mp4",
  ".ogg",
  ".opus",
  ".wav",
]);

function extension(name: string) {
  const index = name.lastIndexOf(".");
  return index < 0 ? "" : name.slice(index).toLowerCase();
}

export function isBookFile(name: string) {
  const lower = name.toLowerCase();
  return lower.endsWith(".epub") || lower.endsWith(".zip");
}

// Supported audiobook files; when an .m4b is present its loose tracks are
// dropped so the same audio is not imported twice.
export function selectAudiobookFiles<F extends Pick<File, "name">>(
  selectedFiles: ArrayLike<F> | null,
) {
  const supported = Array.from(selectedFiles || []).filter((file) =>
    AUDIO_EXTENSIONS.has(extension(file.name)),
  );
  const hasM4b = supported.some((file) => extension(file.name) === ".m4b");
  if (!hasM4b) return supported;
  return supported.filter(
    (file) => !TRACK_EXTENSIONS.has(extension(file.name)),
  );
}

const readDirEntries = (reader: FileSystemDirectoryReader) =>
  new Promise<FileSystemEntry[]>((resolve, reject) =>
    reader.readEntries(resolve, reject),
  );

const getFileFromEntry = (fileEntry: FileSystemEntry) =>
  new Promise<File>((resolve, reject) =>
    (fileEntry as FileSystemFileEntry).file(resolve, reject),
  );

// EPUBs anywhere under dropped folders, plus dropped EPUB and ZIP files.
export async function extractEpubsFromEntries(entries: FileSystemEntry[]) {
  const readDir = async (dirEntry: FileSystemEntry): Promise<File[]> => {
    const reader = (dirEntry as FileSystemDirectoryEntry).createReader();
    const files = [];
    let batch;
    do {
      batch = await readDirEntries(reader);
      for (const entry of batch) {
        if (entry.isFile && entry.name.toLowerCase().endsWith(".epub")) {
          try {
            files.push(await getFileFromEntry(entry));
          } catch {
            // Unreadable files are reported by omission in the selection summary.
          }
        } else if (entry.isDirectory) {
          files.push(...(await readDir(entry)));
        }
      }
    } while (batch.length > 0);
    return files;
  };

  const files = [];
  for (const entry of entries) {
    if (entry.isDirectory) {
      try {
        files.push(...(await readDir(entry)));
      } catch {
        // Ignore unreadable directories.
      }
    } else if (entry.isFile && isBookFile(entry.name)) {
      try {
        files.push(await getFileFromEntry(entry));
      } catch {
        // Ignore unreadable files.
      }
    }
  }
  return files;
}
