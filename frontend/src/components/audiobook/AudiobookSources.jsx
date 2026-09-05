import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  alignImportedAudiobook,
  deleteImportedAudiobook,
  matchImportedAudiobookTrack,
  rebuildAudioOnly,
  rematchImportedAudiobook,
  retryImportedAudiobook,
  upgradeImportedAudiobook,
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

function AudiobookSources({
  bookId,
  chapters = [],
  imports = [],
  aiEnabled = false,
  aiPipelineActive = false,
  onEnableAi,
}) {
  const queryClient = useQueryClient();
  const [jobNotice, setJobNotice] = useState("");
  const [confirmAiTtsRebuild, setConfirmAiTtsRebuild] = useState(false);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["audiobook-imports", bookId] });
    queryClient.invalidateQueries({ queryKey: ["audiobook-chapters", bookId] });
    queryClient.invalidateQueries({ queryKey: ["audiobook-status", bookId] });
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
  const upgradeMutation = useMutation({
    mutationFn: upgradeImportedAudiobook,
    onSuccess: () => {
      setJobNotice("Human audiobook chapter-file upgrade queued.");
      invalidate();
    },
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
        "Audio regeneration queued. Character voices and speaker assignments will be kept.",
      );
      invalidate();
    },
  });

  return (
    <div className="audiobook-sources">
      <section className="audiobook-source-upload">
        <div>
          <h3>Import an audiobook</h3>
          <p>
            Choose a Libation folder, ZIP, or audio files. Include any CUE file
            to keep chapter markers.
          </p>
        </div>
        <a
          className="btn btn-primary"
          href={`/import?type=audiobook&book_id=${bookId}`}
        >
          Import audio files
        </a>
      </section>

      <section className="audiobook-ai-source">
        <div>
          <h3>AI-generated audiobook</h3>
          <p>
            {aiEnabled
              ? "Generated chapters appear in Listen & Read when ready."
              : "Generate narration using your configured AI voices."}
          </p>
        </div>
        {!aiEnabled && (
          <button type="button" onClick={onEnableAi}>
            Enable AI narration
          </button>
        )}
        {aiEnabled && !confirmAiTtsRebuild && (
          <button
            type="button"
            className="btn-primary"
            disabled={aiPipelineActive || aiTtsMutation.isPending}
            onClick={() => setConfirmAiTtsRebuild(true)}
          >
            Regenerate audio only
          </button>
        )}
        {aiEnabled && aiPipelineActive && (
          <p className="hint">
            Pause audio generation before starting again.
          </p>
        )}
        {aiEnabled && confirmAiTtsRebuild && (
          <div className="alignment-note">
            <p>
              Replace the generated audio? Character voices, speaker assignments,
              and imported audiobooks will be kept.
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
                  : "Yes, regenerate audio"}
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
                  <button
                    type="button"
                    disabled={upgradeMutation.isPending}
                    onClick={() => upgradeMutation.mutate(edition.id)}
                  >
                    {upgradeMutation.isPending
                      ? "Queueing…"
                      : edition.needs_upgrade
                        ? "Upgrade Chapter Files"
                        : "Rebuild Chapter Files"}
                  </button>
                  <p className="hint">
                    Source M4B and CUE files are retained. Derived revision{" "}
                    {edition.derived_revision || 0}, format v
                    {edition.derived_format_version || 0}.
                  </p>
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
        upgradeMutation.isError ||
        deleteMutation.isError ||
        matchMutation.isError) && (
        <p className="error">
          {(
            retryMutation.error ||
            alignMutation.error ||
            rematchMutation.error ||
            upgradeMutation.error ||
            deleteMutation.error ||
            matchMutation.error
          )?.message || "Audiobook action failed"}
        </p>
      )}
    </div>
  );
}

export default AudiobookSources;
