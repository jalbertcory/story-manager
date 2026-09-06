import { api, apiUrl, unwrap, unwrapEmpty, multipart } from "./client";
import type { Body } from "./client";

// Pipeline control
export function getAudiobookStatus(bookId: number) {
  return unwrap(
    api.GET("/api/books/{book_id}/audiobook/status", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to fetch audiobook status",
  );
}

export function startPipeline(bookId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/audiobook/start", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to start pipeline",
  );
}

export function stepPipeline(bookId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/audiobook/step", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to run the next pipeline stage",
  );
}

export function runPipelineBatch(bookId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/audiobook/run-batch", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to run one pipeline batch",
  );
}

export function pausePipeline(bookId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/audiobook/pause", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to pause pipeline",
  );
}

export function rebuildPipeline(bookId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/audiobook/rebuild", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to rebuild pipeline",
  );
}

export function rebuildAudioOnly(bookId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/audiobook/audio/rebuild", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to regenerate AI audio",
  );
}

export function setBookTtsProvider(bookId: number, provider: string) {
  return unwrap(
    api.PUT("/api/books/{book_id}/audiobook/tts-provider", {
      params: { path: { book_id: bookId } },
      body: { provider },
    }),
    "Failed to change the audiobook TTS provider",
  );
}

export function rebuildCharacterRoster(bookId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/audiobook/roster/rebuild", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to regenerate the character roster",
  );
}

export function shareCharacterRosterWithSeries(bookId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/audiobook/roster/share-series", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to sync the series character roster",
  );
}

export function generateChapterPreview(bookId: number, chapterId: number) {
  return unwrap(
    api.POST(
      "/api/books/{book_id}/audiobook/chapters/{chapter_id}/preview-audio",
      { params: { path: { book_id: bookId, chapter_id: chapterId } } },
    ),
    "Failed to queue the chapter preview",
  );
}

// Characters
export function getCharacters(bookId: number) {
  return unwrap(
    api.GET("/api/books/{book_id}/audiobook/characters", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to fetch characters",
  );
}

export function updateCharacter(
  charId: number,
  data: Body<"/api/audiobook/characters/{char_id}", "put">,
) {
  return unwrap(
    api.PUT("/api/audiobook/characters/{char_id}", {
      params: { path: { char_id: charId } },
      body: data,
    }),
    "Failed to update character",
  );
}

export function designCharacterVoice(
  charId: number,
  data: Body<"/api/audiobook/characters/{char_id}/design-voice", "post">,
) {
  return unwrap(
    api.POST("/api/audiobook/characters/{char_id}/design-voice", {
      params: { path: { char_id: charId } },
      body: data,
    }),
    "Failed to design a consistent OmniVoice voice",
  );
}

export function getCharacterVoiceSampleUrl(
  charId: number,
  revision: string = "",
) {
  const suffix = revision ? `?revision=${encodeURIComponent(revision)}` : "";
  return (
    apiUrl("/api/audiobook/characters/{char_id}/voice-sample", {
      char_id: charId,
    }) + suffix
  );
}

// Sentences
export function getSentences(
  bookId: number,
  {
    page = 1,
    limit = 50,
    chapterId,
    reviewOnly = false,
  }: {
    page?: number;
    limit?: number;
    chapterId?: number;
    reviewOnly?: boolean;
  } = {},
) {
  return unwrap(
    api.GET("/api/books/{book_id}/audiobook/sentences", {
      params: {
        path: { book_id: bookId },
        query: {
          page,
          limit,
          ...(chapterId !== undefined ? { chapter_id: chapterId } : {}),
          review_only: reviewOnly,
        },
      },
    }),
    "Failed to fetch sentences",
  );
}

export function updateSentence(
  sentenceId: number,
  data: Body<"/api/audiobook/sentences/{sentence_id}", "put">,
) {
  return unwrap(
    api.PUT("/api/audiobook/sentences/{sentence_id}", {
      params: { path: { sentence_id: sentenceId } },
      body: data,
    }),
    "Failed to update sentence",
  );
}

export function generateSentenceAudio(bookId: number, sentenceId: number) {
  return unwrap(
    api.POST(
      "/api/books/{book_id}/audiobook/sentences/{sentence_id}/generate-audio",
      { params: { path: { book_id: bookId, sentence_id: sentenceId } } },
    ),
    "Failed to queue sentence audio",
  );
}

export function getSentenceAudioUrl(sentenceId: number) {
  return apiUrl("/api/audiobook/sentences/{sentence_id}/audio", {
    sentence_id: sentenceId,
  });
}

// Chapters
export function getAudiobookChapters(bookId: number) {
  return unwrap(
    api.GET("/api/books/{book_id}/audiobook/chapters", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to fetch chapters",
  );
}

export function getChapterAudioUrl(bookId: number, chapterId: number) {
  return apiUrl("/api/books/{book_id}/audiobook/chapters/{chapter_id}/audio", {
    book_id: bookId,
    chapter_id: chapterId,
  });
}

export function getAudiobookDownloadUrl(bookId: number) {
  return apiUrl("/api/books/{book_id}/audiobook/download", { book_id: bookId });
}

// Human-narrated audiobook editions
export function getImportedAudiobooks(bookId: number) {
  return unwrap(
    api.GET("/api/books/{book_id}/audiobook/imports", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to fetch imported audiobooks",
  );
}

export function previewLibationBackup(sourcePaths: string[]) {
  return unwrap(
    api.POST("/api/audiobook/libation-backup/preview", {
      body: { source_paths: sourcePaths },
    }),
    "Failed to inspect the Libation backup",
  );
}

export function uploadImportedAudiobook(
  bookId: number | null,
  files: File[],
  name = "",
  autoAlign = true,
  newBook: {
    title?: string;
    inferTitle?: boolean;
    author?: string;
  } | null = null,
) {
  const body = {
    files,
    source_paths: files.map((file) => file.webkitRelativePath || file.name),
    ...(name.trim() ? { name: name.trim() } : {}),
    auto_align: autoAlign,
  };
  if (newBook) {
    return unwrap(
      api.POST("/api/audiobooks/upload", {
        body: {
          ...body,
          title: newBook.title || "",
          infer_title: Boolean(newBook.inferTitle),
          author: newBook.author || "Unknown author",
        },
        bodySerializer: multipart,
      }),
      "Failed to upload audiobook",
    );
  }
  if (bookId === null)
    throw new Error("Choose a book for the audiobook upload.");
  return unwrap(
    api.POST("/api/books/{book_id}/audiobook/imports", {
      params: { path: { book_id: bookId } },
      body,
      bodySerializer: multipart,
    }),
    "Failed to upload audiobook",
  );
}

export function retryImportedAudiobook(editionId: number) {
  return unwrap(
    api.POST("/api/imported-audiobooks/{edition_id}/retry", {
      params: { path: { edition_id: editionId } },
    }),
    "Failed to retry audiobook import",
  );
}

export function upgradeImportedAudiobook(editionId: number) {
  return unwrap(
    api.POST("/api/imported-audiobooks/{edition_id}/upgrade", {
      params: { path: { edition_id: editionId } },
    }),
    "Failed to upgrade audiobook chapter files",
  );
}

export function upgradeAllImportedAudiobooks() {
  return unwrap(
    api.POST("/api/audiobook/imports/upgrade-all"),
    "Failed to queue audiobook upgrades",
  );
}

export function previewHumanAudiobookRebuilds() {
  return unwrap(
    api.GET("/api/audiobook/imports/rebuild-preview"),
    "Failed to inspect human audiobooks",
  );
}

export function rebuildAllHumanAudiobooks({ force = false } = {}) {
  return unwrap(
    api.POST("/api/audiobook/imports/rebuild-all", {
      params: { query: { force } },
    }),
    "Failed to queue human audiobook rebuilds",
  );
}

export function alignImportedAudiobook(editionId: number) {
  return unwrap(
    api.POST("/api/imported-audiobooks/{edition_id}/align", {
      params: { path: { edition_id: editionId } },
    }),
    "Failed to start audiobook timestamp alignment",
  );
}

export function rematchImportedAudiobook(editionId: number) {
  return unwrap(
    api.POST("/api/imported-audiobooks/{edition_id}/rematch", {
      params: { path: { edition_id: editionId } },
    }),
    "Failed to rematch audiobook to book text",
  );
}

export function deleteImportedAudiobook(editionId: number) {
  return unwrapEmpty(
    api.DELETE("/api/imported-audiobooks/{edition_id}", {
      params: { path: { edition_id: editionId } },
    }),
    "Failed to delete imported audiobook",
  );
}

export function matchImportedAudiobookTrack(
  editionId: number,
  trackId: number,
  chapterId: number | null,
) {
  return unwrap(
    api.PUT("/api/imported-audiobooks/{edition_id}/tracks/{track_id}/match", {
      params: { path: { edition_id: editionId, track_id: trackId } },
      body: { chapter_id: chapterId },
    }),
    "Failed to match audiobook track",
  );
}

export function getImportedTrackCues(editionId: number, trackId: number) {
  return unwrap(
    api.GET("/api/imported-audiobooks/{edition_id}/tracks/{track_id}/cues", {
      params: { path: { edition_id: editionId, track_id: trackId } },
    }),
    "Failed to fetch audiobook timing",
  );
}

// Settings
export function getAudiobookSettings() {
  return unwrap(
    api.GET("/api/audiobook/settings"),
    "Failed to fetch audiobook settings",
  );
}

export function updateAudiobookSettings(
  data: Body<"/api/audiobook/settings", "put">,
) {
  return unwrap(
    api.PUT("/api/audiobook/settings", { body: data }),
    "Failed to save audiobook settings",
  );
}

export function getAudiobookEndpointStats() {
  return unwrap(
    api.GET("/api/audiobook/settings/endpoint-stats"),
    "Failed to fetch AI endpoint metrics",
  );
}

export function testAudiobookLlm() {
  return unwrap(
    api.POST("/api/audiobook/settings/test-llm"),
    "Failed to connect to the configured LLM",
  );
}

export function testAudiobookTts() {
  return unwrap(
    api.POST("/api/audiobook/settings/test-tts"),
    "Failed to connect to the configured TTS provider",
  );
}

export function testAudiobookTranscription() {
  return unwrap(
    api.POST("/api/audiobook/settings/test-transcription"),
    "Failed to connect to the transcription service",
  );
}
