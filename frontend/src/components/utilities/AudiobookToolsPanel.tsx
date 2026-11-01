import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  previewHumanAudiobookRebuilds,
  rebuildAllHumanAudiobooks,
} from "../../api/audiobook";
import { queryKeys } from "../../lib/queryKeys";
import ConfirmActionDialog from "../ConfirmActionDialog";

export default function AudiobookToolsPanel() {
  const queryClient = useQueryClient();
  const [audiobookRebuildOpen, setAudiobookRebuildOpen] = useState(false);
  const [audiobookRebuildForce, setAudiobookRebuildForce] = useState(false);
  const [audiobookRebuildNotice, setAudiobookRebuildNotice] = useState("");

  const {
    data: audiobookRebuildPreview,
    isLoading: audiobookRebuildPreviewLoading,
    error: audiobookRebuildPreviewError,
  } = useQuery({
    queryKey: queryKeys.humanAudiobookRebuildPreview,
    queryFn: previewHumanAudiobookRebuilds,
  });

  const audiobookRebuildMutation = useMutation({
    mutationFn: () =>
      rebuildAllHumanAudiobooks({ force: audiobookRebuildForce }),
    onSuccess: (data) => {
      setAudiobookRebuildOpen(false);
      setAudiobookRebuildForce(false);
      setAudiobookRebuildNotice(
        `${data.queued_count} human audiobook rebuild${data.queued_count === 1 ? "" : "s"} queued; ${data.skipped_count} skipped.`,
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.humanAudiobookRebuildPreview,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.processingJobs.all,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.activeProcessingJobs,
      });
    },
  });
  const audiobookRebuildTargetCount = audiobookRebuildForce
    ? (audiobookRebuildPreview?.rebuild_count || 0) +
      (audiobookRebuildPreview?.up_to_date_count || 0)
    : audiobookRebuildPreview?.rebuild_count || 0;

  return (
    <>
      <section className="settings-section">
        <h3>Rebuild Human Audiobooks</h3>
        <p className="hint">
          Update chapter matches and synchronized text for imported audiobooks.
          Original audio and valid manual chapter corrections are kept.
        </p>
        {audiobookRebuildPreviewLoading ? (
          <p className="hint">Inspecting imported audiobooks…</p>
        ) : audiobookRebuildPreviewError ? (
          <p className="error" role="alert">
            {audiobookRebuildPreviewError.message}
          </p>
        ) : audiobookRebuildPreview ? (
          <p className="hint">
            {audiobookRebuildPreview.rebuild_count} of{" "}
            {audiobookRebuildPreview.total_count} edition
            {audiobookRebuildPreview.total_count === 1 ? "" : "s"} need updating
            {audiobookRebuildPreview.realign_count > 0
              ? ` · ${audiobookRebuildPreview.realign_count} need text timing updated`
              : ""}
            {audiobookRebuildPreview.unavailable_count > 0
              ? ` · ${audiobookRebuildPreview.unavailable_count} currently unavailable`
              : ""}
          </p>
        ) : null}
        <div className="settings-actions">
          <button
            type="button"
            onClick={() => {
              setAudiobookRebuildForce(false);
              setAudiobookRebuildOpen(true);
            }}
            disabled={
              audiobookRebuildPreviewLoading ||
              !audiobookRebuildPreview?.rebuild_count ||
              audiobookRebuildMutation.isPending
            }
          >
            Rebuild outdated human audiobooks
          </button>
          <button
            type="button"
            className="btn-text"
            onClick={() => {
              setAudiobookRebuildForce(true);
              setAudiobookRebuildOpen(true);
            }}
            disabled={
              audiobookRebuildPreviewLoading ||
              !(
                (audiobookRebuildPreview?.rebuild_count || 0) +
                (audiobookRebuildPreview?.up_to_date_count || 0)
              ) ||
              audiobookRebuildMutation.isPending
            }
          >
            Force rebuild all ready editions
          </button>
        </div>
        {audiobookRebuildNotice && (
          <p className="success">{audiobookRebuildNotice}</p>
        )}
        {audiobookRebuildMutation.isError && (
          <p className="error" role="alert">
            {audiobookRebuildMutation.error.message}
          </p>
        )}
      </section>
      <section className="settings-section">
        <h3>Libation Backup Import</h3>
        <p className="hint">
          Choose a backup and review which books its audiobooks belong to.
        </p>
        <a className="btn btn-primary" href="/import?type=libation">
          Import Libation backup
        </a>
      </section>
      <ConfirmActionDialog
        open={audiobookRebuildOpen}
        title={
          audiobookRebuildForce
            ? "Force rebuild all ready human audiobooks?"
            : "Rebuild outdated human audiobooks?"
        }
        confirmLabel="Queue rebuilds"
        busyLabel="Queueing…"
        isPending={audiobookRebuildMutation.isPending}
        onCancel={() => {
          setAudiobookRebuildOpen(false);
          setAudiobookRebuildForce(false);
        }}
        onConfirm={() => audiobookRebuildMutation.mutate()}
      >
        <p>
          This will queue {audiobookRebuildTargetCount} imported edition
          {audiobookRebuildTargetCount === 1 ? "" : "s"} for updated chapter
          matching and text timing.
        </p>
        {audiobookRebuildForce && (
          <p>
            <strong>This also rebuilds editions already marked current.</strong>
          </p>
        )}
        <p>
          Original audio and manual chapter corrections are preserved.
          Compatible cached transcripts are reused; if a required transcript is
          missing or incompatible, the configured transcription service will be
          called again.
        </p>
      </ConfirmActionDialog>
    </>
  );
}
