import type { Schemas } from "../api/client";

// The server derives one state per audiobook source (see
// backend/app/services/audiobook_status.py); the UI only chooses its colour.
export type AudioState = Schemas["AudiobookOverviewSource"]["state"];
export type AudioNextAction = NonNullable<
  Schemas["AudiobookOverviewSource"]["next_action"]
>;

type Tone = "danger" | "warning" | "active" | "success" | "neutral";

const TONES: Record<AudioState, Tone> = {
  job_failed: "danger",
  import_failed: "danger",
  tts_failed: "danger",
  // The audio still plays; only synchronized text waits for the review.
  needs_review: "warning",
  whisper_failed: "warning",
  outdated: "warning",
  tts_outdated: "warning",
  tts_paused: "warning",
  working: "active",
  tts_running: "active",
  tts_partial: "neutral",
  tts_not_started: "neutral",
  ready_estimated: "neutral",
  audio_only: "neutral",
  ready_whisper: "success",
  tts_complete: "success",
};

export const ACTIVE_AUDIO_STATES: ReadonlySet<AudioState> = new Set([
  "working",
  "tts_running",
]);

export function audioStateTone(state: AudioState): Tone {
  return TONES[state];
}

export function audioStateClass(state: AudioState) {
  return `audio-state audio-state--${TONES[state]}`;
}

// Actions that queue a job for one human edition, as opposed to links. These
// are also the actions the bulk endpoint accepts.
export type EditionJobAction = Schemas["AudiobookBulkActionRequest"]["action"];

const EDITION_JOB_ACTIONS: ReadonlySet<string> = new Set<EditionJobAction>([
  "retry_processing",
  "retry_import",
  "rebuild",
  "retry_whisper",
  "improve_with_whisper",
]);

export function isEditionJobAction(
  action: AudioNextAction,
): action is EditionJobAction {
  return EDITION_JOB_ACTIONS.has(action);
}

export function audioActionHref(
  action: AudioNextAction,
  bookId: number,
): string | null {
  switch (action) {
    case "review_matches":
      return `/books/${bookId}/audiobooks?tab=sources`;
    case "set_up_transcription":
      return "/settings/audio-ai";
    case "open_generation":
      return `/books/${bookId}/audiobooks?tab=progress`;
    default:
      return null;
  }
}
