import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createBackup,
  deleteBackup,
  getBackups,
  verifyBackup,
} from "../../api/backups";
import { getProcessingJobs } from "../../api/processing";
import { formatBytes } from "../../lib/format";
import ConfirmActionDialog from "../ConfirmActionDialog";

export default function BackupsPanel() {
  const queryClient = useQueryClient();
  const [backupDeleteTarget, setBackupDeleteTarget] = useState<
    | NonNullable<Awaited<ReturnType<typeof getBackups>>["backups"]>[number]
    | null
  >(null);
  const { data: backupJobs = [] } = useQuery({
    queryKey: ["backup-jobs"],
    queryFn: () => getProcessingJobs({ limit: 100 }),
    select: (jobs) =>
      jobs.filter((job) =>
        ["create_backup", "verify_backup"].includes(job.job_type),
      ),
    refetchInterval: ({ state }) =>
      (state.data || []).some((job) =>
        ["queued", "running"].includes(job.status),
      )
        ? 3000
        : false,
  });
  const activeBackupJob = backupJobs.find((job) =>
    ["queued", "running"].includes(job.status),
  );
  const latestBackupJob = backupJobs[0];

  const { data: backupInventory, isLoading: backupsLoading } = useQuery({
    queryKey: ["backups"],
    queryFn: getBackups,
    refetchInterval: activeBackupJob ? 3000 : false,
  });
  const backups = backupInventory?.backups || [];

  useEffect(() => {
    if (latestBackupJob?.completed_at)
      queryClient.invalidateQueries({ queryKey: ["backups"] });
  }, [latestBackupJob?.completed_at, queryClient]);

  const createBackupMutation = useMutation({
    mutationFn: createBackup,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["backup-jobs"] }),
  });

  const verifyBackupMutation = useMutation({
    mutationFn: verifyBackup,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["backup-jobs"] }),
  });

  const deleteBackupMutation = useMutation({
    mutationFn: deleteBackup,
    onSuccess: () => {
      setBackupDeleteTarget(null);
      queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
  });

  return (
    <>
      <section className="settings-section">
        <p className="hint">
          Back up your book details and library files. Changes are briefly
          paused while the backup is created and checked.
        </p>
        <div className="settings-actions">
          <button
            type="button"
            onClick={() => createBackupMutation.mutate()}
            disabled={
              Boolean(activeBackupJob) || createBackupMutation.isPending
            }
          >
            {activeBackupJob?.job_type === "create_backup"
              ? activeBackupJob.progress_detail || "Creating backup…"
              : "Create backup"}
          </button>
        </div>

        {latestBackupJob?.status === "error" && (
          <p className="error">
            {latestBackupJob.error || latestBackupJob.progress_detail}
          </p>
        )}
        {activeBackupJob && (
          <p className="hint" aria-live="polite">
            {activeBackupJob.progress_detail || "Backup work is running…"}
          </p>
        )}
        {(createBackupMutation.isError ||
          verifyBackupMutation.isError ||
          deleteBackupMutation.isError) && (
          <p className="error">
            {
              (
                createBackupMutation.error ||
                verifyBackupMutation.error ||
                deleteBackupMutation.error
              )?.message
            }
          </p>
        )}

        <div className="backup-restore-warning">
          <strong>Stop Story Manager before restoring a backup.</strong>
          <span>
            Use the command below to replace your current library with a backup.
          </span>
        </div>
        <details className="backup-restore-details">
          <summary>Show restore command</summary>
          <p className="hint">
            Run this from the directory containing your Docker Compose file:
          </p>
          <code>docker compose stop story-manager</code>
          <code>
            docker compose run --rm story-manager ./run-container.sh restore
            /app/backups/&lt;filename&gt; --confirm-replace
          </code>
          <p className="hint">
            Start Story Manager again only after the restore command succeeds.
          </p>
        </details>

        <h4>Available backups</h4>
        {backupInventory && (
          <p className="hint">
            {backupInventory.retention_count === 0
              ? "Backups are kept until you delete them."
              : `The newest ${backupInventory.retention_count} backup${backupInventory.retention_count === 1 ? " is" : "s are"} kept automatically.`}
          </p>
        )}
        {backupsLoading ? (
          <p className="hint">Loading backups…</p>
        ) : backups.length === 0 ? (
          <p className="hint">No backups have been created yet.</p>
        ) : (
          <ul className="backup-list">
            {backups.map((backup) => (
              <li className="backup-list-item" key={backup.filename}>
                <div>
                  <strong>
                    {new Date(backup.created_at).toLocaleString()}
                  </strong>
                  <p className="hint">
                    {formatBytes(backup.size_bytes)} ·{" "}
                    {backup.library_file_count} library file
                    {backup.library_file_count === 1 ? "" : "s"} ·{" "}
                    {formatBytes(backup.library_size_bytes)} of library data
                  </p>
                  <p
                    className={
                      backup.valid_manifest ? "backup-status-ok" : "error"
                    }
                  >
                    {backup.valid_manifest && backup.verified_at_creation
                      ? "✓ Checksums verified when created"
                      : backup.error || "Manifest could not be validated"}
                  </p>
                </div>
                <div className="backup-actions">
                  <a
                    className="btn btn-secondary"
                    href={backup.download_url}
                    download
                  >
                    Download
                  </a>
                  <button
                    type="button"
                    onClick={() => verifyBackupMutation.mutate(backup.filename)}
                    disabled={
                      Boolean(activeBackupJob) || verifyBackupMutation.isPending
                    }
                  >
                    Verify now
                  </button>
                  <button
                    type="button"
                    className="btn-danger"
                    onClick={() => setBackupDeleteTarget(backup)}
                    disabled={
                      Boolean(activeBackupJob) || deleteBackupMutation.isPending
                    }
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <ConfirmActionDialog
        open={Boolean(backupDeleteTarget)}
        title="Delete this backup?"
        confirmLabel="Delete backup"
        busyLabel="Deleting…"
        danger
        isPending={deleteBackupMutation.isPending}
        onCancel={() => setBackupDeleteTarget(null)}
        onConfirm={() =>
          backupDeleteTarget &&
          deleteBackupMutation.mutate(backupDeleteTarget.filename)
        }
      >
        <p>{backupDeleteTarget?.filename}</p>
        <p>
          <strong>
            This removes the only copy of this backup from Story Manager and
            cannot be undone.
          </strong>
        </p>
      </ConfirmActionDialog>
    </>
  );
}
