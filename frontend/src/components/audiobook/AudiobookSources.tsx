import type { Chapter, ImportedEdition } from "./types";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import ConfirmActionDialog from "../ConfirmActionDialog";

import {
  alignImportedAudiobook,
  deleteImportedAudiobook,
  matchImportedAudiobookTrack,
  rebuildAudioOnly,
  rebuildImportedAudiobook,
  rematchImportedAudiobook,
  retryImportedAudiobook,
  upgradeImportedAudiobook,
} from "../../api/audiobook";
import { chapterLabel } from "../../lib/audiobook";
import { audioStateClass, audioStateTone } from "../../lib/audioState";
import { queryKeys } from "../../lib/queryKeys";
import { retryProcessingJob } from "../../api/processing";

function durationLabel(durationMs: number | null | undefined) {
  if (!durationMs) return "—";
  const seconds = Math.round(durationMs / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function importedAtLabel(createdAt: string | null | undefined) {
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
  audioOnly = false,
  aiPipelineActive = false,
  onEnableAi,
}: {
  bookId: number;
  chapters?: Chapter[];
  imports?: ImportedEdition[];
  aiEnabled?: boolean;
  audioOnly?: boolean;
  aiPipelineActive?: boolean;
  onEnableAi?: (() => void) | undefined;
}) {
  const queryClient = useQueryClient();
  const [jobNotice, setJobNotice] = useState("");
  const [confirmAiTtsRebuild, setConfirmAiTtsRebuild] = useState(false);
  const [editionToDelete, setEditionToDelete] = useState<{
    id: number;
    name: string;
  } | null>(null);

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.audiobook.imports(bookId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.audiobook.chapters(bookId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.audiobook.status(bookId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.audiobookOverview,
    });
  };
  const retryMutation = useMutation({
    mutationFn: retryImportedAudiobook,
    onSuccess: () => {
      setJobNotice("Human audiobook import retry queued.");
      invalidate();
    },
  });
  const retryProcessingMutation = useMutation({
    mutationFn: retryProcessingJob,
    onSuccess: () => {
      setJobNotice("Human audiobook processing retry queued.");
      invalidate();
    },
  });
  const deleteMutation = useMutation({
    mutationFn: deleteImportedAudiobook,
    onSuccess: invalidate,
    onSettled: () => setEditionToDelete(null),
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
  const rebuildMutation = useMutation({
    mutationFn: rebuildImportedAudiobook,
    onSuccess: () => {
      setJobNotice("Human audiobook rebuild queued.");
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
    mutationFn: ({
      editionId,
      trackId,
      chapterId,
    }: {
      editionId: number;
      trackId: number;
      chapterId: number | null;
    }) => matchImportedAudiobookTrack(editionId, trackId, chapterId),
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

      {!audioOnly && (
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
                Replace the generated audio? Character voices, speaker
                assignments, and imported audiobooks will be kept.
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
            <p className="error" role="alert">
              {aiTtsMutation.error.message}
            </p>
          )}
        </section>
      )}
      {!imports.length ? (
        <p className="empty-state">No human-narrated editions imported yet.</p>
      ) : (
        imports.map((edition) => {
          const working = edition.state === "working";
          const matched = edition.tracks.filter(
            (track) => track.matched_chapter_id != null,
          ).length;
          const tone = audioStateTone(edition.state);
          const next = edition.next_action;
          const jobId = edition.processing_job_id;
          const isReady = edition.status === "ready";
          const canRematch =
            !audioOnly && !working && edition.tracks.length > 0;
          // Rebuild realigns an outdated edition, and alignment needs valid
          // matches and a transcription provider.
          const canAlign =
            !audioOnly &&
            isReady &&
            ["ready_estimated", "ready_whisper", "whisper_failed"].includes(
              edition.state,
            ) &&
            next !== "set_up_transcription";
          const alignLabel =
            edition.alignment_method === "estimated"
              ? "Improve timestamps with Whisper"
              : "Re-align with Whisper";
          const rematchButton = (primary: boolean) => (
            <button
              type="button"
              className={primary ? "btn-primary" : undefined}
              aria-label={`Rematch ${edition.name} to book text`}
              disabled={rematchMutation.isPending}
              onClick={() => rematchMutation.mutate(edition.id)}
            >
              {rematchMutation.isPending ? "Queueing…" : "Rematch to book text"}
            </button>
          );
          const queueButton = (
            label: string,
            mutation: { isPending: boolean; mutate: (id: number) => void },
          ) => (
            <button
              type="button"
              className="btn-primary"
              disabled={mutation.isPending}
              onClick={() => mutation.mutate(edition.id)}
            >
              {mutation.isPending ? "Queueing…" : label}
            </button>
          );
          const label = edition.next_action_label ?? "";
          const primaryAction =
            next === "retry_processing" && jobId != null ? (
              <button
                type="button"
                className="btn-primary"
                disabled={retryProcessingMutation.isPending}
                onClick={() => retryProcessingMutation.mutate(jobId)}
              >
                {retryProcessingMutation.isPending ? "Queueing…" : label}
              </button>
            ) : next === "retry_import" ? (
              queueButton(label, retryMutation)
            ) : next === "rebuild" ? (
              queueButton(label, rebuildMutation)
            ) : next === "retry_whisper" || next === "improve_with_whisper" ? (
              queueButton(label, alignMutation)
            ) : next === "review_matches" && canRematch ? (
              rematchButton(true)
            ) : next === "set_up_transcription" ? (
              <a href="/settings/audio-ai">{label}</a>
            ) : null;
          const alignIsPrimary =
            next === "retry_whisper" || next === "improve_with_whisper";
          // Raw messages the state summary does not already show.
          const technical = [
            edition.error,
            edition.matching_error,
            edition.alignment_error,
          ].filter(
            (message, index, all): message is string =>
              Boolean(message) &&
              message !== edition.state_detail &&
              all.indexOf(message) === index,
          );
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
                    <span className="audio-state audio-state--success">
                      Reader app default
                    </span>
                  )}
                  <span className={audioStateClass(edition.state)}>
                    {edition.state_label}
                  </span>
                </div>
              </header>
              {working ? (
                <div className="import-progress" role="status">
                  <p>{edition.state_detail || "Working…"}</p>
                  {edition.progress_total > 0 && (
                    <progress
                      value={edition.progress_current}
                      max={edition.progress_total}
                    />
                  )}
                </div>
              ) : (
                edition.state_detail && (
                  <p
                    className={
                      tone === "danger"
                        ? "error"
                        : tone === "warning"
                          ? "alignment-note"
                          : "hint"
                    }
                    role={tone === "danger" ? "alert" : undefined}
                  >
                    {edition.state_detail}
                  </p>
                )
              )}
              {primaryAction && (
                <div className="imported-edition-actions">{primaryAction}</div>
              )}
              {!working && edition.tracks.length > 0 && (
                <details open={edition.state === "needs_review"}>
                  <summary>Track matching and more options</summary>
                  <div className="imported-edition-actions">
                    {canRematch &&
                      next !== "review_matches" &&
                      rematchButton(false)}
                    {canAlign && !alignIsPrimary && (
                      <button
                        type="button"
                        disabled={alignMutation.isPending}
                        onClick={() => alignMutation.mutate(edition.id)}
                      >
                        {alignMutation.isPending ? "Queueing…" : alignLabel}
                      </button>
                    )}
                    {isReady && (
                      <button
                        type="button"
                        disabled={upgradeMutation.isPending}
                        onClick={() => upgradeMutation.mutate(edition.id)}
                      >
                        {upgradeMutation.isPending
                          ? "Queueing…"
                          : "Rebuild chapter files"}
                      </button>
                    )}
                  </div>
                  {technical.map((message) => (
                    <p className="hint" key={message}>
                      {message}
                    </p>
                  ))}
                  <p className="hint">
                    Source audio and CUE files are kept. Pipeline v
                    {edition.pipeline_version}, chapter file format v
                    {edition.derived_format_version}, revision{" "}
                    {edition.derived_revision}.
                  </p>
                  <div className="imported-track-list">
                    {edition.tracks.map((track) => (
                      <label key={track.id}>
                        <span>
                          {track.title}
                          <small>
                            {durationLabel(track.duration_ms)} ·{" "}
                            {audioOnly
                              ? "Audio only"
                              : `${track.cue_count} text cues`}
                            {track.alignment_score != null
                              ? ` · ${Math.round(track.alignment_score * 100)}% aligned`
                              : ""}
                          </small>
                        </span>
                        {!audioOnly && (
                          <select
                            aria-label={`Book chapter for ${track.title}`}
                            value={track.matched_chapter_id ?? ""}
                            disabled={
                              !isReady && edition.state !== "needs_review"
                            }
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
                        )}
                      </label>
                    ))}
                  </div>
                </details>
              )}
              <button
                type="button"
                className="btn-text imported-edition-delete"
                disabled={working || deleteMutation.isPending}
                onClick={() =>
                  setEditionToDelete({ id: edition.id, name: edition.name })
                }
              >
                Delete imported edition
              </button>
            </section>
          );
        })
      )}
      <ConfirmActionDialog
        open={editionToDelete != null}
        title={`Delete imported edition “${editionToDelete?.name ?? ""}”?`}
        confirmLabel="Delete edition"
        busyLabel="Deleting…"
        danger
        isPending={deleteMutation.isPending}
        onCancel={() => setEditionToDelete(null)}
        onConfirm={() => {
          if (editionToDelete) deleteMutation.mutate(editionToDelete.id);
        }}
      >
        <p>Its stored audio files are deleted too. This cannot be undone.</p>
      </ConfirmActionDialog>
      {jobNotice && (
        <p className="job-queued-notice" role="status">
          {jobNotice} <a href="/activity/processing">View processing</a>
        </p>
      )}
      {(retryMutation.isError ||
        retryProcessingMutation.isError ||
        rebuildMutation.isError ||
        alignMutation.isError ||
        rematchMutation.isError ||
        upgradeMutation.isError ||
        deleteMutation.isError ||
        matchMutation.isError) && (
        <p className="error" role="alert">
          {(
            retryMutation.error ||
            retryProcessingMutation.error ||
            rebuildMutation.error ||
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
