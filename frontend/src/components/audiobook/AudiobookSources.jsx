import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  alignImportedAudiobook,
  deleteImportedAudiobook,
  matchImportedAudiobookTrack,
  rebuildAudioOnly,
  rematchImportedAudiobook,
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

function importedAtLabel(createdAt) {
  if (!createdAt) return "Import date unavailable";
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return "Import date unavailable";
  return `Imported ${new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)}`;
}

const AUDIO_EXTENSIONS = new Set([
  ".aac",
  ".flac",
  ".m4a",
  ".m4b",
  ".mp3",
  ".mp4",
  ".ogg",
  ".opus",
  ".wav",
]);
const IMPORT_EXTENSIONS = new Set([...AUDIO_EXTENSIONS, ".cue", ".zip"]);

function extension(file) {
  const index = file.name.lastIndexOf(".");
  return index < 0 ? "" : file.name.slice(index).toLowerCase();
}

function selectAudiobookFiles(selectedFiles) {
  const supported = selectedFiles.filter((file) =>
    IMPORT_EXTENSIONS.has(extension(file)),
  );
  const hasM4b = supported.some((file) => extension(file) === ".m4b");
  if (!hasM4b) return supported;
  return supported.filter(
    (file) =>
      !AUDIO_EXTENSIONS.has(extension(file)) || extension(file) === ".m4b",
  );
}

function AudiobookSources({
  bookId,
  chapters = [],
  imports = [],
  aiEnabled = false,
  aiPipelineActive = false,
  onEnableAi,
}) {
  const queryClient = useQueryClient();
  const inputRef = useRef(null);
  const directoryInputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [name, setName] = useState("");
  const [autoAlign, setAutoAlign] = useState(true);
  const [ignoredFileCount, setIgnoredFileCount] = useState(0);
  const [jobNotice, setJobNotice] = useState("");
  const [confirmAiTtsRebuild, setConfirmAiTtsRebuild] = useState(false);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["audiobook-imports", bookId] });
    queryClient.invalidateQueries({ queryKey: ["audiobook-chapters", bookId] });
    queryClient.invalidateQueries({ queryKey: ["audiobook-status", bookId] });
  };
  const uploadMutation = useMutation({
    mutationFn: () => uploadImportedAudiobook(bookId, files, name, autoAlign),
    onSuccess: () => {
      setJobNotice("Human audiobook import and matching queued.");
      setFiles([]);
      setName("");
      setIgnoredFileCount(0);
      if (inputRef.current) inputRef.current.value = "";
      if (directoryInputRef.current) directoryInputRef.current.value = "";
      invalidate();
    },
  });
  const chooseFiles = (selectedFiles) => {
    const selected = Array.from(selectedFiles || []);
    const usable = selectAudiobookFiles(selected);
    setFiles(usable);
    setIgnoredFileCount(selected.length - usable.length);
  };
  const retryMutation = useMutation({
    mutationFn: retryImportedAudiobook,
    onSuccess: () => {
      setJobNotice("Human audiobook import retry queued.");
      invalidate();
    },
  });
  const deleteMutation = useMutation({
    mutationFn: deleteImportedAudiobook,
    onSuccess: invalidate,
  });
  const alignMutation = useMutation({
    mutationFn: alignImportedAudiobook,
    onSuccess: () => {
      setJobNotice("Human audiobook timestamp alignment queued.");
      invalidate();
    },
  });
  const rematchMutation = useMutation({
    mutationFn: rematchImportedAudiobook,
    onSuccess: () => {
      setJobNotice("Human audiobook chapter rematch queued.");
      invalidate();
    },
  });
  const matchMutation = useMutation({
    mutationFn: ({ editionId, trackId, chapterId }) =>
      matchImportedAudiobookTrack(editionId, trackId, chapterId),
    onSuccess: invalidate,
  });
  const aiTtsMutation = useMutation({
    mutationFn: () => rebuildAudioOnly(bookId),
    onSuccess: () => {
      setConfirmAiTtsRebuild(false);
      setJobNotice(
        "AI TTS-only regeneration queued; speaker analysis preserved.",
      );
      invalidate();
    },
  });

  return (
    <div className="audiobook-sources">
      <section className="audiobook-source-upload">
        <div>
          <span className="metric-label">Human narration</span>
          <h3>Import an audiobook</h3>
          <p>
            Select a Libation book folder unchanged, upload its ZIP, or choose
            M4B, MP3, M4A, and CUE files together. Story Manager prefers the
            chapter-capable M4B when Libation also created a duplicate MP3.
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
          Libation book directory
          <input
            ref={directoryInputRef}
            type="file"
            multiple
            webkitdirectory=""
            directory=""
            onChange={(event) => chooseFiles(event.target.files)}
          />
        </label>
        <label>
          Or audiobook file / ZIP
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".zip,.cue,.m4b,.m4a,.mp3,.mp4,.aac,.flac,.ogg,.opus,.wav,audio/*"
            onChange={(event) => chooseFiles(event.target.files)}
          />
        </label>
        {files.length > 0 && (
          <p className="audiobook-selected-files">
            {files.map((file) => file.name).join(", ")}
          </p>
        )}
        {ignoredFileCount > 0 && (
          <p className="hint">
            Ignored {ignoredFileCount} duplicate or non-audio{" "}
            {ignoredFileCount === 1 ? "file" : "files"}.
          </p>
        )}
        <label>
          <input
            type="checkbox"
            checked={autoAlign}
            onChange={(event) => setAutoAlign(event.target.checked)}
          />{" "}
          Improve sentence timestamps with Whisper after matching
        </label>
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
        {aiEnabled && !confirmAiTtsRebuild && (
          <button
            type="button"
            className="btn-primary"
            disabled={aiPipelineActive || aiTtsMutation.isPending}
            onClick={() => setConfirmAiTtsRebuild(true)}
          >
            Regenerate AI TTS Only
          </button>
        )}
        {aiEnabled && aiPipelineActive && (
          <p className="hint">
            Pause the active AI pipeline before regenerating TTS.
          </p>
        )}
        {aiEnabled && confirmAiTtsRebuild && (
          <div className="alignment-note">
            <p>
              Replace AI TTS clips and assembly only? The roster, speaker
              assignments, and imported human audiobooks will be preserved.
            </p>
            <div className="confirm-inline">
              <button
                type="button"
                className="btn-primary"
                disabled={aiTtsMutation.isPending}
                onClick={() => aiTtsMutation.mutate()}
              >
                {aiTtsMutation.isPending
                  ? "Queueing…"
                  : "Yes, regenerate AI TTS"}
              </button>
              <button
                type="button"
                className="btn-text"
                disabled={aiTtsMutation.isPending}
                onClick={() => setConfirmAiTtsRebuild(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
        {aiTtsMutation.isError && (
          <p className="error">{aiTtsMutation.error.message}</p>
        )}
      </section>

      {!imports.length ? (
        <p className="empty-state">No human-narrated editions imported yet.</p>
      ) : (
        imports.map((edition) => {
          const active = ["stale", "queued", "importing", "aligning"].includes(
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
                  <p>
                    <time dateTime={edition.created_at}>
                      {importedAtLabel(edition.created_at)}
                    </time>
                  </p>
                </div>
                <div className="imported-edition-badges">
                  {edition.is_reader_default && (
                    <span className="badge badge--success">
                      Reader app default
                    </span>
                  )}
                  <span
                    className={`badge${edition.status === "error" ? " badge--error" : active ? " badge--warning" : ""}`}
                  >
                    {edition.status}
                  </span>
                </div>
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
                  {edition.tracks.length > 0 && matched === 0 && (
                    <div className="alignment-note">
                      <p>
                        The imported audio is intact, but its chapter matches
                        and synchronized text need to be restored.
                      </p>
                      <button
                        type="button"
                        className="btn-primary"
                        aria-label={`Rematch ${edition.name} to book text`}
                        disabled={rematchMutation.isPending}
                        onClick={() => rematchMutation.mutate(edition.id)}
                      >
                        {rematchMutation.isPending
                          ? "Queueing…"
                          : "Rematch to Book Text"}
                      </button>
                    </div>
                  )}
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
      {jobNotice && (
        <p className="job-queued-notice" role="status">
          {jobNotice} <a href="/processing">View processing</a>
        </p>
      )}
      {(retryMutation.isError ||
        alignMutation.isError ||
        rematchMutation.isError ||
        deleteMutation.isError ||
        matchMutation.isError) && (
        <p className="error">
          {(
            retryMutation.error ||
            alignMutation.error ||
            rematchMutation.error ||
            deleteMutation.error ||
            matchMutation.error
          )?.message || "Audiobook action failed"}
        </p>
      )}
    </div>
  );
}

export default AudiobookSources;
