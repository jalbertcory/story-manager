import type { components } from "../../api/schema";
export type Chapter = components["schemas"]["ChapterResponse"];
export type Character = components["schemas"]["CharacterResponse"];
export type Sentence = components["schemas"]["SentenceResponse"];
export type AudioStatus = components["schemas"]["AudiobookStatusResponse"];
export type ImportedEdition =
  components["schemas"]["ImportedAudiobookResponse"];
export type ReadingCue = Pick<
  components["schemas"]["ImportedCueResponse"],
  | "sentence_id"
  | "text"
  | "clip_begin_ms"
  | "clip_end_ms"
  | "reading_block_index"
  | "reading_block_type"
>;
