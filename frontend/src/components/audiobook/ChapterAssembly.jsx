import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  generateChapterPreview,
  getChapterAudioUrl,
} from "../../api/audiobook";

function ChapterAssembly({ chapters, bookId, pipelineActive = false }) {
  const queryClient = useQueryClient();
  const previewMutation = useMutation({
    mutationFn: (chapterId) => generateChapterPreview(bookId, chapterId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["audiobook-chapters", bookId],
      });
      queryClient.invalidateQueries({ queryKey: ["audiobook-status", bookId] });
    },
  });
  if (!chapters || chapters.length === 0) {
    return (
      <p className="empty-state">
        No chapters yet. Start the pipeline to begin processing.
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
            const previewBusy = ["queued", "generating"].includes(
              chapter.preview_status,
            );
            const previewReady =
              chapter.audio_file_path && !chapter.needs_reassembly;
            return (
              <tr key={chapter.id}>
                <td>Chapter {chapter.chapter_number}</td>
                <td>
                  {previewBusy ? (
                    <span className="badge badge--warning">
                      {chapter.preview_status === "queued"
                        ? "Queued"
                        : "Generating"}{" "}
                      · {chapter.audio_generated_count}/{chapter.sentence_count}
                    </span>
                  ) : chapter.preview_status === "error" ? (
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
                          ? "Pause the full-book pipeline first"
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
