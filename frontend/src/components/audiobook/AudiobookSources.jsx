import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  alignImportedAudiobook,
  deleteImportedAudiobook,
  matchImportedAudiobookTrack,
  retryImportedAudiobook,
  uploadImportedAudiobook,
} from "../../api/audiobook";
import { chapterLabel } from "../../lib/audiobook";

function durationLabel(durationMs) {
  if (!durationMs) return "—";
  const seconds = Math.round(durationMs / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function AudiobookSources({
  bookId,
  chapters = [],
  imports = [],
  aiEnabled = false,
  onEnableAi,
}) {
  const queryClient = useQueryClient();
  const inputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [name, setName] = useState("");

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["audiobook-imports", bookId] });
    queryClient.invalidateQueries({ queryKey: ["audiobook-chapters", bookId] });
  };
  const uploadMutation = useMutation({
    mutationFn: () => uploadImportedAudiobook(bookId, files, name),
    onSuccess: () => {
      setFiles([]);
      setName("");
      if (inputRef.current) inputRef.current.value = "";
      invalidate();
    },
  });
  const retryMutation = useMutation({
    mutationFn: retryImportedAudiobook,
    onSuccess: invalidate,
  });
  const deleteMutation = useMutation({
    mutationFn: deleteImportedAudiobook,
    onSuccess: invalidate,
  });
  const alignMutation = useMutation({
    mutationFn: alignImportedAudiobook,
    onSuccess: invalidate,
  });
  const matchMutation = useMutation({
    mutationFn: ({ editionId, trackId, chapterId }) =>
      matchImportedAudiobookTrack(editionId, trackId, chapterId),
    onSuccess: invalidate,
  });

  return (
    <div className="audiobook-sources">
      <section className="audiobook-source-upload">
        <div>
          <span className="metric-label">Human narration</span>
          <h3>Import an audiobook</h3>
          <p>
            Upload a Libation ZIP unchanged, or select M4B, MP3, M4A, and CUE
            files together. CUE and embedded chapter titles are matched against
            this book automatically.
          </p>
        </div>
        <label>
          Edition name (optional)
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="For example, Audible / Jeff Hays"
          />
        </label>
        <label>
          Audiobook file or files
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".zip,.cue,.m4b,.m4a,.mp3,.mp4,.aac,.flac,.ogg,.opus,.wav,audio/*"
            onChange={(event) => setFiles(Array.from(event.target.files || []))}
          />
        </label>
        {files.length > 0 && (
          <p className="audiobook-selected-files">
            {files.map((file) => file.name).join(", ")}
          </p>
        )}
        <button
          type="button"
          className="btn-primary"
          disabled={!files.length || uploadMutation.isPending}
          onClick={() => uploadMutation.mutate()}
        >
          {uploadMutation.isPending ? "Uploading…" : "Upload & Match"}
        </button>
        {uploadMutation.isPending && (
          <p className="hint" role="status">
            Large Libation archives can take a few minutes to transfer. Keep
            this page open until the upload finishes; matching continues in the
            background afterward.
          </p>
        )}
        {uploadMutation.isError && (
          <p className="error">{uploadMutation.error.message}</p>
        )}
      </section>

      <section className="audiobook-ai-source">
        <div>
          <span className="metric-label">Synthetic narration</span>
          <h3>AI-generated audiobook</h3>
          <p>
            {aiEnabled
              ? "Enabled. Its generated chapters appear as another edition in Listen & Read."
              : "Optional. Enable the existing LLM + text-to-speech pipeline if you also want a generated edition."}
          </p>
        </div>
        {!aiEnabled && (
          <button type="button" onClick={onEnableAi}>
            Enable AI Audiobook Pipeline
          </button>
        )}
      </section>

      {!imports.length ? (
        <p className="empty-state">No human-narrated editions imported yet.</p>
      ) : (
        imports.map((edition) => {
          const active = ["queued", "importing", "aligning"].includes(
            edition.status,
          );
          const matched = edition.tracks.filter(
            (track) => track.matched_chapter_id != null,
          ).length;
          return (
            <section className="imported-edition-card" key={edition.id}>
              <header className="imported-edition-header">
                <div>
                  <span className="metric-label">
                    {edition.source_type}
                    {edition.asin ? ` · ${edition.asin}` : ""}
                  </span>
                  <h3>{edition.name}</h3>
                  <p>
                    {durationLabel(edition.duration_ms)} · {matched} of{" "}
                    {edition.tracks.length} tracks matched
                  </p>
                </div>
                <span
                  className={`badge${edition.status === "error" ? " badge--error" : active ? " badge--warning" : ""}`}
                >
                  {edition.status}
                </span>
              </header>
              {active && (
                <div className="import-progress" role="status">
                  <p>{edition.progress_detail || "Working…"}</p>
                  {edition.progress_total > 0 && (
                    <progress
                      value={edition.progress_current}
                      max={edition.progress_total}
                    />
                  )}
                </div>
              )}
              {edition.error && <p className="error">{edition.error}</p>}
              {edition.alignment_error && (
                <p className="error">{edition.alignment_error}</p>
              )}
              {edition.status === "error" && (
                <button
                  type="button"
                  onClick={() => retryMutation.mutate(edition.id)}
                  disabled={retryMutation.isPending}
                >
                  Retry Import
                </button>
              )}
              {edition.status === "ready" && (
                <>
                  <p className="alignment-note">
                    {edition.alignment_method === "transcribed"
                      ? "Sentence timestamps are aligned to WhisperX word timestamps."
                      : edition.alignment_method === "hybrid"
                        ? "Transcribed timestamps are active; uncertain passages retain estimated timing."
                        : "Sentence highlighting currently uses spoken-text length estimates and may drift within a chapter."}
                  </p>
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={alignMutation.isPending}
                    onClick={() => alignMutation.mutate(edition.id)}
                  >
                    {alignMutation.isPending
                      ? "Queueing…"
                      : edition.alignment_method === "estimated"
                        ? "Improve Timestamps with Whisper"
                        : "Re-align Timestamps"}
                  </button>
                  {edition.progress_detail && (
                    <p className="hint">{edition.progress_detail}</p>
                  )}
                  <details>
                    <summary>Review track matching</summary>
                    <div className="imported-track-list">
                      {edition.tracks.map((track) => (
                        <label key={track.id}>
                          <span>
                            {track.title}
                            <small>
                              {durationLabel(track.duration_ms)} ·{" "}
                              {track.cue_count} text cues
                              {track.alignment_score != null
                                ? ` · ${Math.round(track.alignment_score * 100)}% aligned`
                                : ""}
                            </small>
                          </span>
                          <select
                            value={track.matched_chapter_id ?? ""}
                            onChange={(event) =>
                              matchMutation.mutate({
                                editionId: edition.id,
                                trackId: track.id,
                                chapterId: event.target.value
                                  ? Number(event.target.value)
                                  : null,
                              })
                            }
                          >
                            <option value="">Not matched</option>
                            {chapters.map((chapter) => (
                              <option key={chapter.id} value={chapter.id}>
                                {chapterLabel(chapter)}
                              </option>
                            ))}
                          </select>
                        </label>
                      ))}
                    </div>
                  </details>
                </>
              )}
              <button
                type="button"
                className="btn-text imported-edition-delete"
                disabled={active || deleteMutation.isPending}
                onClick={() => {
                  if (
                    window.confirm(
                      `Delete imported edition “${edition.name}” and its stored audio?`,
                    )
                  ) {
                    deleteMutation.mutate(edition.id);
                  }
                }}
              >
                Delete imported edition
              </button>
            </section>
          );
        })
      )}
      {(retryMutation.isError ||
        alignMutation.isError ||
        deleteMutation.isError ||
        matchMutation.isError) && (
        <p className="error">
          {(
            retryMutation.error ||
            alignMutation.error ||
            deleteMutation.error ||
            matchMutation.error
          )?.message || "Audiobook action failed"}
        </p>
      )}
    </div>
  );
}

export default AudiobookSources;
