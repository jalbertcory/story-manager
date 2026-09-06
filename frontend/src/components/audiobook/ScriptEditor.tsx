import type { components } from "../../api/schema";
import type { Chapter, Character, Sentence } from "./types";
import { useState } from "react";
import {
  keepPreviousData,
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import {
  generateSentenceAudio,
  getSentences,
  updateSentence,
  getSentenceAudioUrl,
} from "../../api/audiobook";
import { chapterLabel } from "../../lib/audiobook";
import useLifecycleDefinitions from "../../hooks/useLifecycleDefinitions";

const STATUS_ICONS: Record<string, string> = {
  pending_diarization: "⏳",
  ready_for_audio: "🎙",
  audio_queued: "⏱",
  audio_generating: "🔊",
  audio_generated: "✅",
  error: "❌",
};

function SentenceRow({
  sentence,
  characters,
  bookId,
  pipelineActive,
  statusLabels,
  statusGroups,
}: {
  sentence: Sentence;
  characters: Character[];
  bookId: number;
  pipelineActive: boolean;
  statusLabels: Record<string, string>;
  statusGroups: Record<
    "playable" | "ready" | "waiting" | "working" | "inProgress" | "failed",
    Set<string | null>
  >;
}) {
  const queryClient = useQueryClient();
  const [tags, setTags] = useState(
    sentence.tagged_text || sentence.original_text,
  );
  const [characterId, setCharacterId] = useState<number | string>(
    sentence.character_id ?? "",
  );
  const [editing, setEditing] = useState(false);

  const mutation = useMutation({
    mutationFn: (data: components["schemas"]["SentenceUpdate"]) =>
      updateSentence(sentence.id, data),
    onSuccess: () => {
      setEditing(false);
      void queryClient.invalidateQueries({
        queryKey: ["audiobook-sentences", bookId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["audiobook-status", bookId],
      });
    },
  });

  const audioMutation = useMutation({
    mutationFn: () => generateSentenceAudio(bookId, sentence.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["audiobook-sentences", bookId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["audiobook-status", bookId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["audiobook-chapters", bookId],
      });
    },
  });

  const handleSave = () => {
    mutation.mutate({
      character_id: characterId !== "" ? Number(characterId) : null,
      tagged_text: tags,
    });
  };

  const statusInfo = {
    icon: STATUS_ICONS[sentence.status] || "?",
    label: statusLabels[sentence.status] || sentence.status,
  };
  const audioUrl = statusGroups.playable.has(sentence.status)
    ? getSentenceAudioUrl(sentence.id)
    : null;

  return (
    <tr className={`sentence-row sentence-row--${sentence.status}`}>
      <td className="sentence-seq">{sentence.sequence_order}</td>
      <td className="sentence-text">{sentence.original_text}</td>
      <td className="sentence-tags">
        {editing ? (
          <input
            type="text"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            className="sentence-tags-input"
          />
        ) : (
          <span onClick={() => setEditing(true)} title="Click to edit">
            {tags}
          </span>
        )}
      </td>
      <td className="sentence-speaker">
        <select
          value={characterId}
          onChange={(e) => {
            setCharacterId(e.target.value);
            setEditing(true);
          }}
        >
          <option value="">— unassigned —</option>
          {characters.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </td>
      <td
        className="sentence-confidence"
        title={sentence.speaker_reason || "No model rationale"}
      >
        {sentence.speaker_confidence == null ? (
          "—"
        ) : (
          <span
            className={`confidence-badge${
              sentence.speaker_confidence < 0.65 ? " confidence-badge--low" : ""
            }`}
          >
            {Math.round(sentence.speaker_confidence * 100)}%
          </span>
        )}
      </td>
      <td className="sentence-status" title={statusInfo.label}>
        <span aria-hidden="true">{statusInfo.icon}</span>
        <span>{statusInfo.label}</span>
        {(sentence.voice_similarity != null ||
          sentence.tts_attempts != null ||
          sentence.generation_group_id) && (
          <small
            title={`Generated in ${sentence.tts_attempts || 1} attempt(s)`}
          >
            {sentence.voice_similarity != null
              ? `Voice ${sentence.voice_similarity.toFixed(2)}`
              : "Voice check n/a"}
            {(sentence.tts_attempts ?? 0) > 1
              ? ` · ${sentence.tts_attempts} attempts`
              : ""}
            {sentence.generation_group_id ? " · block" : ""}
          </small>
        )}
      </td>
      <td className="sentence-audio">
        {audioUrl ? (
          <audio
            controls
            src={audioUrl}
            preload="none"
            style={{ height: "24px" }}
          />
        ) : statusGroups.ready.has(sentence.status) ||
          statusGroups.failed.has(sentence.status) ? (
          <button
            type="button"
            className="btn-small"
            onClick={() => audioMutation.mutate()}
            disabled={
              audioMutation.isPending ||
              pipelineActive ||
              editing ||
              characterId === ""
            }
            title={
              pipelineActive
                ? "Pause book-wide audio generation first"
                : editing
                  ? "Save sentence edits before generating audio"
                  : characterId === ""
                    ? "Assign a speaker first"
                    : "Generate only this sentence with its current voice profile"
            }
          >
            {audioMutation.isPending
              ? "Queueing…"
              : statusGroups.failed.has(sentence.status)
                ? "Retry audio"
                : "Generate audio"}
          </button>
        ) : statusGroups.inProgress.has(sentence.status) ? (
          <span className="sentence-audio-progress">
            {statusGroups.waiting.has(sentence.status)
              ? "Waiting…"
              : "Working…"}
          </span>
        ) : null}
        {audioMutation.isError && (
          <span className="error sentence-audio-error">
            {audioMutation.error?.message}
          </span>
        )}
      </td>
      <td className="sentence-actions">
        {editing && (
          <>
            <button
              onClick={handleSave}
              disabled={mutation.isPending}
              className="btn-small"
            >
              {mutation.isPending ? "…" : "Save"}
            </button>
            <button
              onClick={() => {
                setTags(sentence.tagged_text || sentence.original_text);
                setCharacterId(sentence.character_id ?? "");
                setEditing(false);
              }}
              className="btn-small btn-text"
            >
              Cancel
            </button>
          </>
        )}
        {mutation.isError && (
          <span className="error">{mutation.error?.message}</span>
        )}
      </td>
    </tr>
  );
}

function ScriptEditor({
  bookId,
  characters,
  chapters = [],
  pipelineActive = false,
}: {
  bookId: number;
  characters: Character[];
  chapters?: Chapter[];
  pipelineActive?: boolean;
}) {
  const { data: lifecycleDefinitions } = useLifecycleDefinitions();
  const sentenceLifecycle = lifecycleDefinitions?.sentence;
  const statusLabels = Object.fromEntries<string>(
    (sentenceLifecycle?.states ?? []).map((state) => [
      String(state.value),
      state.label,
    ]),
  );
  const audioInProgressStatuses = new Set(
    sentenceLifecycle?.groups?.audio_in_progress ?? [],
  );
  const audioReadyStatuses = new Set(
    sentenceLifecycle?.groups?.audio_ready ?? [],
  );
  const audioWaitingStatuses = new Set(
    sentenceLifecycle?.groups?.audio_waiting ?? [],
  );
  const audioWorkingStatuses = new Set(
    sentenceLifecycle?.groups?.audio_working ?? [],
  );
  const audioPlayableStatuses = new Set(
    sentenceLifecycle?.groups?.audio_playable ?? [],
  );
  const failedStatuses = new Set(sentenceLifecycle?.failure_states ?? []);
  const statusGroups = {
    inProgress: audioInProgressStatuses,
    ready: audioReadyStatuses,
    waiting: audioWaitingStatuses,
    working: audioWorkingStatuses,
    playable: audioPlayableStatuses,
    failed: failedStatuses,
  };
  const [page, setPage] = useState(1);
  const [chapterFilter, setChapterFilter] = useState("");
  const [reviewOnly, setReviewOnly] = useState(false);
  const limit = 50;

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["audiobook-sentences", bookId, page, chapterFilter, reviewOnly],
    queryFn: () =>
      getSentences(bookId, {
        page,
        limit,
        ...(chapterFilter ? { chapterId: Number(chapterFilter) } : {}),
        reviewOnly,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: ({ state }) =>
      state.data?.items?.some((sentence) =>
        audioInProgressStatuses.has(sentence.status),
      )
        ? 1500
        : false,
  });

  if (isLoading) return <p>Loading sentences…</p>;
  if (isError)
    return (
      <p className="error">{error?.message || "Failed to load sentences"}</p>
    );

  const { items = [], total = 0 } = data || {};
  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="script-editor">
      <div className="script-editor-controls">
        <span>{total} sentences</span>
        <label>
          Chapter
          <select
            value={chapterFilter}
            onChange={(event) => {
              setChapterFilter(event.target.value);
              setPage(1);
            }}
          >
            <option value="">All</option>
            {chapters.map((chapter) => (
              <option key={chapter.id} value={chapter.id}>
                {chapterLabel(chapter)} · {chapter.processed_sentence_count}/
                {chapter.sentence_count}
              </option>
            ))}
          </select>
        </label>
        <label className="review-filter">
          <input
            type="checkbox"
            checked={reviewOnly}
            onChange={(event) => {
              setReviewOnly(event.target.checked);
              setPage(1);
            }}
          />
          Needs review only
        </label>
        <div className="pagination">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
          >
            ‹ Prev
          </button>
          <span>
            Page {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
          >
            Next ›
          </button>
        </div>
      </div>

      {items.length === 0 ? (
        <p className="empty-state">
          No sentences yet. Start AI narration to prepare the text.
        </p>
      ) : (
        <div className="script-table-wrap">
          <table className="script-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Original Text</th>
                <th>Tags</th>
                <th>Speaker</th>
                <th>Confidence</th>
                <th>Status</th>
                <th>Audio</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((sentence) => (
                <SentenceRow
                  key={sentence.id}
                  sentence={sentence}
                  characters={characters}
                  bookId={bookId}
                  pipelineActive={pipelineActive}
                  statusLabels={statusLabels}
                  statusGroups={statusGroups}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default ScriptEditor;
