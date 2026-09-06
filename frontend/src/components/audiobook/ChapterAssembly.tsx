import type { Chapter } from "./types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  generateChapterPreview,
  getChapterAudioUrl,
} from "../../api/audiobook";
import { chapterLabel } from "../../lib/audiobook";
import useLifecycleDefinitions from "../../hooks/useLifecycleDefinitions";

function ChapterAssembly({
  chapters,
  bookId,
  pipelineActive = false,
}: {
  chapters: Chapter[];
  bookId: number;
  pipelineActive?: boolean;
}) {
  const queryClient = useQueryClient();
  const { data: lifecycleDefinitions } = useLifecycleDefinitions();
  const previewLifecycle = lifecycleDefinitions?.chapter_preview;
  const previewLabels = Object.fromEntries<string>(
    (previewLifecycle?.states ?? []).map((state) => [
      String(state.value),
      state.label,
    ]),
  );
  const activePreviewStatuses = new Set(previewLifecycle?.active_states ?? []);
  const failedPreviewStatuses = new Set(previewLifecycle?.failure_states ?? []);
  const previewMutation = useMutation({
    mutationFn: (chapterId: number) =>
      generateChapterPreview(bookId, chapterId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["audiobook-chapters", bookId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["audiobook-status", bookId],
      });
    },
  });
  if (!chapters || chapters.length === 0) {
    return (
      <p className="empty-state">
        No chapters yet. Start AI narration to prepare them.
      </p>
    );
  }

  return (
    <div className="chapter-assembly">
      <table className="chapter-table">
        <thead>
          <tr>
            <th>Chapter</th>
            <th>Assembly Status</th>
            <th>Audio Preview</th>
            <th>Manual Action</th>
            <th>SMIL</th>
          </tr>
        </thead>
        <tbody>
          {chapters.map((chapter) => {
            const analyzed =
              chapter.sentence_count > 0 &&
              chapter.processed_sentence_count === chapter.sentence_count;
            const previewBusy = activePreviewStatuses.has(
              chapter.preview_status,
            );
            const previewReady =
              chapter.audio_file_path && !chapter.needs_reassembly;
            return (
              <tr key={chapter.id}>
                <td>{chapterLabel(chapter)}</td>
                <td>
                  {previewBusy ? (
                    <span className="badge badge--warning">
                      {previewLabels[chapter.preview_status ?? ""] ??
                        chapter.preview_status}{" "}
                      · {chapter.audio_generated_count}/{chapter.sentence_count}
                    </span>
                  ) : failedPreviewStatuses.has(chapter.preview_status) ? (
                    <span className="badge badge--error">Preview failed</span>
                  ) : chapter.needs_reassembly ? (
                    <span className="badge badge--warning">
                      Rebuild Pending
                    </span>
                  ) : chapter.audio_file_path ? (
                    <span className="badge badge--success">Assembled</span>
                  ) : (
                    <span className="badge badge--neutral">
                      Not yet assembled
                    </span>
                  )}
                </td>
                <td>
                  {previewReady && (
                    <audio
                      controls
                      src={getChapterAudioUrl(bookId, chapter.id)}
                      preload="none"
                      style={{ height: "28px" }}
                    />
                  )}
                </td>
                <td>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => previewMutation.mutate(chapter.id)}
                    disabled={
                      !analyzed ||
                      pipelineActive ||
                      previewBusy ||
                      previewMutation.isPending
                    }
                    title={
                      !analyzed
                        ? `Analyze all ${chapter.sentence_count} sentences first`
                        : pipelineActive
                          ? "Pause book-wide audio generation first"
                          : "Generate audio using the current voice profiles"
                    }
                  >
                    {previewBusy
                      ? "Working…"
                      : previewReady
                        ? "Rebuild Preview"
                        : "Generate Preview"}
                  </button>
                  {!analyzed && (
                    <small className="chapter-preview-hint">
                      {chapter.processed_sentence_count}/
                      {chapter.sentence_count} analyzed
                    </small>
                  )}
                  {chapter.preview_error && (
                    <small className="error chapter-preview-error">
                      {chapter.preview_error}
                    </small>
                  )}
                </td>
                <td>
                  {chapter.smil_file_path && !chapter.needs_reassembly && (
                    <a
                      href={`/library/audiobooks/${bookId}/${chapter.smil_file_path.split("/").pop()}`}
                      download
                      className="btn-text"
                    >
                      Download SMIL
                    </a>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="chapter-preview-note">
        Chapter previews are manual and use the current shared voice profiles.
        Rebuild a preview after tuning a voice; the full audiobook remains
        paused.
      </p>
      {previewMutation.isError && (
        <p className="error">{previewMutation.error?.message}</p>
      )}
    </div>
  );
}

export default ChapterAssembly;
