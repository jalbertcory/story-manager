import { stringValue, displayValue } from "../lib/errors";
import { formatBytes } from "../lib/format";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveMetadataMatch,
  getLatestMetadataJob,
  getMetadataInbox,
  queueMetadataSync,
  rejectMetadataMatch,
} from "../api/metadata";
import ReaderKeys from "./ReaderKeys";
import ConfirmActionDialog from "./ConfirmActionDialog";
import {
  getRecycleBin,
  permanentlyDeleteRecycledBook,
  restoreRecycledBook,
} from "../api/books";
import BackupsPanel from "./utilities/BackupsPanel";
import {
  previewHumanAudiobookRebuilds,
  rebuildAllHumanAudiobooks,
} from "../api/audiobook";

const utilityPages = [
  { key: "audit", label: "Library Audit" },
  { key: "series", label: "Detect Series" },
  { key: "metadata", label: "Sync Online Metadata" },
  { key: "audiobooks", label: "Audiobooks" },
  { key: "recycle-bin", label: "Recycle Bin" },
  { key: "storage", label: "Storage Cleanup" },
  { key: "backups", label: "Backup & Restore" },
  { key: "reader-access", label: "Reader API Keys" },
];

function getRequestedUtilityTab() {
  const requested = new URLSearchParams(window.location.search).get("section");
  return utilityPages.some((tab) => tab.key === requested)
    ? requested
    : "audit";
}

import {
  cleanupStorage as runCleanup,
  validateLibrary as runLibraryValidation,
} from "../api/admin";
import { detectSeries } from "../api/imports";
type CleanupPreview = Awaited<ReturnType<typeof runCleanup>>;
type MetadataEntry = NonNullable<
  Awaited<ReturnType<typeof getMetadataInbox>>[number]["candidate_matches"]
>[number];

function formatAuditIssue(issue: { issue: string }) {
  switch (issue.issue) {
    case "pending_web_import":
      return "pending web import";
    case "failed_web_import":
      return "failed web import";
    default:
      return issue.issue.replace(/_/g, " ");
  }
}

function getCleanupFiles(preview: CleanupPreview | null) {
  return preview?.files || [];
}

function getCleanupBooks(preview: CleanupPreview | null) {
  return preview?.books || [];
}

function getCleanupTargetCount(preview: CleanupPreview | null) {
  return getCleanupFiles(preview).length + getCleanupBooks(preview).length;
}

function formatCleanupSummary(preview: CleanupPreview | null) {
  const parts = [];
  const fileCount = getCleanupFiles(preview).length;
  const bookCount = getCleanupBooks(preview).length;

  if (fileCount > 0) {
    parts.push(`${fileCount} file${fileCount !== 1 ? "s" : ""}`);
  }
  if (bookCount > 0) {
    parts.push(`${bookCount} failed import${bookCount !== 1 ? "s" : ""}`);
  }

  return parts.join(", ");
}

function renderMetadataJobSummary(
  job: Awaited<ReturnType<typeof getLatestMetadataJob>> | undefined,
) {
  if (!job) return "No metadata sync jobs have run yet.";
  const base = `${job.processed_books}/${job.total_books} processed, ${job.matched_books} matched, ${job.proposed_books} proposed, ${job.applied_books} applied.`;
  if (job.status === "failed" && job.error) {
    return `${base} Failed: ${job.error}`;
  }
  return base;
}

function formatMetadataMatchOption(match: MetadataEntry) {
  const title = match.remote_title || "Unknown title";
  const author = match.remote_author ? ` by ${match.remote_author}` : "";
  const confidence =
    match.match_confidence != null
      ? ` (${Math.round(match.match_confidence * 100)}%)`
      : "";
  const provider = match.source
    ? ` · ${match.source
        .split("+")
        .map((source) => source.replaceAll("_", " "))
        .join(" + ")}`
    : "";
  return `${title}${author}${confidence}${provider}`;
}

function Utilities({
  onBack,
  section,
  reviewOnly = false,
}: {
  onBack?: () => void;
  section?: string;
  reviewOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState(
    () => section || getRequestedUtilityTab(),
  );
  const [metadataPage, setMetadataPage] = useState(0);
  const [preview, setPreview] = useState<CleanupPreview | null>(null);
  const [detectState, setDetectState] = useState<
    | (Awaited<ReturnType<typeof detectSeries>> & { error?: boolean })
    | "pending"
    | null
  >(null); // null | "pending" | { updated, series_detected, error? }
  const [selectedMatchIds, setSelectedMatchIds] = useState<
    Record<number, number>
  >({});
  const [permanentDeleteTarget, setPermanentDeleteTarget] = useState<
    | NonNullable<Awaited<ReturnType<typeof getRecycleBin>>["books"]>[number]
    | null
  >(null);
  const [audiobookRebuildOpen, setAudiobookRebuildOpen] = useState(false);
  const [audiobookRebuildForce, setAudiobookRebuildForce] = useState(false);
  const [audiobookRebuildNotice, setAudiobookRebuildNotice] = useState("");

  useEffect(() => {
    const onPopState = () => setActiveTab(section || getRequestedUtilityTab());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [section]);

  const previewMutation = useMutation({
    mutationFn: () => runCleanup(true),
    onSuccess: (data) => setPreview(data),
  });

  const deleteMutation = useMutation({
    mutationFn: () => runCleanup(false),
    onSuccess: (data) => setPreview(data),
  });

  const isPending = previewMutation.isPending || deleteMutation.isPending;
  const deleted = preview && !preview.dry_run;

  const validateMutation = useMutation({
    mutationFn: runLibraryValidation,
  });

  const { data: latestMetadataJob } = useQuery({
    queryKey: ["metadata-job-latest"],
    queryFn: getLatestMetadataJob,
    staleTime: 5000,
    refetchOnWindowFocus: false,
    refetchInterval: ({ state }) =>
      state.data?.status === "running" || state.data?.status === "queued"
        ? 5000
        : false,
  });

  const {
    data: metadataInbox = [],
    isLoading: inboxLoading,
    error: inboxError,
  } = useQuery({
    queryKey: ["metadata-inbox", metadataPage],
    queryFn: () => getMetadataInbox({ offset: metadataPage * 20, limit: 21 }),
    staleTime: 15000,
    refetchOnWindowFocus: false,
    refetchInterval:
      latestMetadataJob?.status === "running" ||
      latestMetadataJob?.status === "queued"
        ? 15000
        : false,
  });

  const queueMetadataMutation = useMutation({
    mutationFn: () => queueMetadataSync(null, "manual"),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["metadata-job-latest"] });
    },
  });

  const approveMatchMutation = useMutation({
    mutationFn: (matchId: number) => approveMetadataMatch(matchId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      void queryClient.invalidateQueries({ queryKey: ["metadata-inbox"] });
      void queryClient.invalidateQueries({ queryKey: ["attention-dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["metadata-job-latest"] });
    },
  });

  const rejectMatchMutation = useMutation({
    mutationFn: (matchId: number) => rejectMetadataMatch(matchId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["metadata-inbox"] });
      void queryClient.invalidateQueries({ queryKey: ["attention-dashboard"] });
    },
  });

  const validationResult = validateMutation.data;

  const { data: recycleBin, isLoading: recycleBinLoading } = useQuery({
    queryKey: ["recycle-bin"],
    queryFn: getRecycleBin,
    enabled: activeTab === "recycle-bin",
  });

  const restoreBookMutation = useMutation({
    mutationFn: restoreRecycledBook,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["recycle-bin"] });
      void queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      void queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });

  const permanentDeleteMutation = useMutation({
    mutationFn: permanentlyDeleteRecycledBook,
    onSuccess: () => {
      setPermanentDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["recycle-bin"] });
    },
  });

  const {
    data: audiobookRebuildPreview,
    isLoading: audiobookRebuildPreviewLoading,
    error: audiobookRebuildPreviewError,
  } = useQuery({
    queryKey: ["human-audiobook-rebuild-preview"],
    queryFn: previewHumanAudiobookRebuilds,
    enabled: activeTab === "audiobooks",
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
        queryKey: ["human-audiobook-rebuild-preview"],
      });
      void queryClient.invalidateQueries({ queryKey: ["processing-jobs"] });
      void queryClient.invalidateQueries({
        queryKey: ["active-processing-jobs"],
      });
    },
  });
  const audiobookRebuildTargetCount = audiobookRebuildForce
    ? (audiobookRebuildPreview?.rebuild_count || 0) +
      (audiobookRebuildPreview?.up_to_date_count || 0)
    : audiobookRebuildPreview?.rebuild_count || 0;

  const handleDetectSeries = async () => {
    setDetectState("pending");
    try {
      const data = await detectSeries();
      if (data.updated > 0) {
        void queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      }
      setDetectState(data);
    } catch {
      setDetectState({ updated: 0, series_detected: [], error: true });
    }
  };

  return (
    <div className={`${onBack ? "book-settings " : ""}utilities-page`}>
      <div className="settings-header">
        {onBack && (
          <button
            className="btn-text"
            onClick={onBack}
            style={{ flexShrink: 0 }}
          >
            ← Back
          </button>
        )}
        <h2>
          {reviewOnly
            ? "Review suggestions"
            : utilityPages.find((page) => page.key === activeTab)?.label}
        </h2>
      </div>

      <div className="sub-tab-content utilities-tab-content">
        {activeTab === "audit" && (
          <section className="settings-section">
            <p className="hint">Find missing EPUB files and covers.</p>
            <div className="settings-actions">
              <button
                onClick={() => validateMutation.mutate()}
                disabled={validateMutation.isPending}
              >
                {validateMutation.isPending
                  ? "Auditing..."
                  : "Run Library Audit"}
              </button>
              {validationResult && (
                <button
                  className="btn-text"
                  onClick={() => validateMutation.reset()}
                >
                  Reset
                </button>
              )}
            </div>
            {validateMutation.isError && (
              <p className="error" style={{ marginTop: "0.5rem" }}>
                {validateMutation.error?.message}
              </p>
            )}
            {validationResult && (
              <div style={{ marginTop: "1rem" }}>
                <h4>
                  {validationResult.issues_count === 0
                    ? "No Issues Found"
                    : "Issues Found"}
                  <span
                    className="hint"
                    style={{ fontWeight: "normal", marginLeft: "0.5rem" }}
                  >
                    {validationResult.total_books} book
                    {validationResult.total_books !== 1
                      ? "s"
                      : ""} checked, {validationResult.issues_count} issue
                    {validationResult.issues_count !== 1 ? "s" : ""}
                  </span>
                </h4>
                {validationResult.issues_count === 0 ? (
                  <p className="hint">
                    All books have valid file paths. Library is healthy.
                  </p>
                ) : (
                  <ul
                    style={{
                      listStyle: "none",
                      padding: 0,
                      margin: 0,
                      display: "flex",
                      flexDirection: "column",
                      gap: "0.35rem",
                    }}
                  >
                    {validationResult.issues.map((issue, i) => (
                      <li
                        key={i}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "baseline",
                          fontSize: "0.85rem",
                          padding: "0.4rem 0.6rem",
                          borderRadius: "4px",
                          background: "var(--surface, #1a1a2e)",
                          gap: "1rem",
                        }}
                      >
                        <span style={{ wordBreak: "break-word" }}>
                          <strong>{issue.title}</strong>
                          {issue.author && (
                            <span className="hint"> by {issue.author}</span>
                          )}
                        </span>
                        <span
                          style={{
                            flexShrink: 0,
                            color: "#f87171",
                            fontFamily: "monospace",
                            fontSize: "0.8rem",
                          }}
                        >
                          {formatAuditIssue(issue)}
                          {issue.path && (
                            <span
                              className="hint"
                              style={{ marginLeft: "0.5rem" }}
                            >
                              {issue.path}
                            </span>
                          )}
                          {!issue.path && issue.source_url && (
                            <span
                              className="hint"
                              style={{ marginLeft: "0.5rem" }}
                            >
                              {issue.source_url}
                            </span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </section>
        )}

        {activeTab === "series" && (
          <section className="settings-section">
            <p className="hint">
              Assigns series names found in book titles to books without a
              series.
            </p>
            <div className="settings-actions">
              <button
                onClick={() => {
                  void handleDetectSeries();
                }}
                disabled={detectState === "pending"}
              >
                {detectState === "pending"
                  ? "Detecting…"
                  : "Detect Series in Library"}
              </button>
            </div>
            {detectState && detectState !== "pending" && (
              <p
                className={detectState.error ? "error" : "hint"}
                style={{ marginTop: "0.5rem" }}
              >
                {detectState.error
                  ? "Error running detection."
                  : detectState.updated === 0
                    ? "No new series found."
                    : `Updated ${detectState.updated} book${detectState.updated > 1 ? "s" : ""}: ${detectState.series_detected.join(", ")}`}
              </p>
            )}
          </section>
        )}

        {activeTab === "metadata" && (
          <section className="settings-section">
            <p className="hint">
              Looks up book details online. Uncertain matches appear below for
              review.
            </p>
            <div className="settings-actions">
              <button
                onClick={() => queueMetadataMutation.mutate()}
                disabled={queueMetadataMutation.isPending}
              >
                {queueMetadataMutation.isPending
                  ? "Queueing…"
                  : "Queue Library Metadata Sync"}
              </button>
            </div>
            {(queueMetadataMutation.isError ||
              approveMatchMutation.isError ||
              rejectMatchMutation.isError) && (
              <p className="error" style={{ marginTop: "0.5rem" }}>
                {
                  (
                    queueMetadataMutation.error ||
                    approveMatchMutation.error ||
                    rejectMatchMutation.error
                  )?.message
                }
              </p>
            )}
            <div style={{ marginTop: "1rem" }}>
              <p className="hint">
                Last book details check:{" "}
                {latestMetadataJob
                  ? latestMetadataJob.status
                  : "Not checked yet"}
              </p>
              <p className="hint">
                {renderMetadataJobSummary(latestMetadataJob)}
              </p>
            </div>
            <div style={{ marginTop: "1rem" }}>
              <h4>
                Metadata Inbox
                <span
                  className="hint"
                  style={{ fontWeight: "normal", marginLeft: "0.5rem" }}
                >
                  Page {metadataPage + 1} · {Math.min(metadataInbox.length, 20)}{" "}
                  suggestions
                </span>
              </h4>
            </div>
            {inboxLoading && <p role="status">Loading suggestions…</p>}
            {inboxError && (
              <p role="alert" className="error">
                {inboxError.message}
              </p>
            )}
            {metadataInbox.length > 0 ? (
              <div style={{ marginTop: "1rem" }}>
                <ul
                  style={{
                    listStyle: "none",
                    padding: 0,
                    margin: 0,
                    display: "grid",
                    gap: "0.75rem",
                  }}
                >
                  {metadataInbox.slice(0, 20).map((entry) => (
                    <li
                      key={entry.id}
                      style={{
                        border: "1px solid rgba(148, 163, 184, 0.2)",
                        borderRadius: "8px",
                        padding: "0.75rem",
                        background: "rgba(15, 23, 42, 0.35)",
                      }}
                    >
                      {(() => {
                        const candidateMatches = (
                          entry.candidate_matches?.length
                            ? entry.candidate_matches
                            : entry.match
                              ? [entry.match]
                              : []
                        ).filter((match) => match.status === "pending");
                        const selectedMatchId =
                          selectedMatchIds[entry.id] ??
                          entry.match?.id ??
                          candidateMatches[0]?.id;
                        const selectedMatch =
                          candidateMatches.find(
                            (match) => match.id === Number(selectedMatchId),
                          ) || entry.match;
                        const proposedGenres =
                          selectedMatch?.proposed_genre_tags ??
                          entry.proposed_genre_tags ??
                          [];
                        const possibleMissingSeries =
                          selectedMatch?.possible_missing_series_books ??
                          entry.possible_missing_series_books ??
                          [];
                        const matchIssues = selectedMatch?.match_issues ?? [];
                        const candidateSeries = stringValue(
                          selectedMatch?.remote_metadata?.series,
                        );
                        const candidateSeriesIndex = displayValue(
                          selectedMatch?.remote_metadata?.series_index,
                        );
                        const evidenceNote = selectedMatch?.note ?? entry.note;

                        return (
                          <>
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                gap: "1rem",
                                alignItems: "flex-start",
                              }}
                            >
                              <div>
                                <strong>{entry.book_title}</strong>
                                <span
                                  className="hint"
                                  style={{ marginLeft: "0.5rem" }}
                                >
                                  {selectedMatch?.status || entry.status}
                                </span>
                              </div>
                              <div
                                className="settings-actions"
                                style={{ marginTop: 0, flexShrink: 0 }}
                              >
                                {selectedMatch?.status === "pending" &&
                                selectedMatch?.id ? (
                                  <>
                                    <button
                                      onClick={() =>
                                        approveMatchMutation.mutate(
                                          selectedMatch.id,
                                        )
                                      }
                                      disabled={
                                        approveMatchMutation.isPending ||
                                        rejectMatchMutation.isPending
                                      }
                                    >
                                      {approveMatchMutation.isPending
                                        ? "Approving…"
                                        : "Approve Match"}
                                    </button>
                                    <button
                                      className="btn-danger"
                                      onClick={() =>
                                        rejectMatchMutation.mutate(
                                          selectedMatch.id,
                                        )
                                      }
                                      disabled={
                                        approveMatchMutation.isPending ||
                                        rejectMatchMutation.isPending
                                      }
                                    >
                                      {rejectMatchMutation.isPending
                                        ? "Rejecting…"
                                        : "Reject Match"}
                                    </button>
                                  </>
                                ) : null}
                              </div>
                            </div>
                            <p
                              className="hint"
                              style={{ marginTop: "0.35rem" }}
                            >
                              {entry.book_author}
                            </p>
                            {candidateMatches.length > 1 ? (
                              <label
                                className="hint"
                                style={{
                                  display: "grid",
                                  gap: "0.35rem",
                                  marginTop: "0.5rem",
                                }}
                              >
                                Suggested match
                                <select
                                  value={selectedMatchId || ""}
                                  onChange={(event) =>
                                    setSelectedMatchIds((current) => ({
                                      ...current,
                                      [entry.id]: Number(event.target.value),
                                    }))
                                  }
                                >
                                  {candidateMatches.map((match) => (
                                    <option key={match.id} value={match.id}>
                                      {formatMetadataMatchOption(match)}
                                    </option>
                                  ))}
                                </select>
                              </label>
                            ) : (
                              selectedMatch && (
                                <p
                                  className="hint"
                                  style={{ marginTop: "0.5rem" }}
                                >
                                  Suggested match:{" "}
                                  {formatMetadataMatchOption(selectedMatch)}
                                </p>
                              )
                            )}
                            {(entry.book_series || candidateSeries) && (
                              <p
                                className="hint"
                                style={{ marginTop: "0.5rem" }}
                              >
                                Local series: {entry.book_series || "Unknown"}
                                {entry.book_series_index != null
                                  ? ` #${entry.book_series_index}`
                                  : ""}
                                {" · "}
                                Candidate series: {candidateSeries || "Unknown"}
                                {candidateSeriesIndex != null
                                  ? ` #${candidateSeriesIndex}`
                                  : ""}
                              </p>
                            )}
                            {proposedGenres.length > 0 && (
                              <p
                                className="hint"
                                style={{ marginTop: "0.5rem" }}
                              >
                                Proposed genres: {proposedGenres.join(", ")}
                              </p>
                            )}
                            {matchIssues.length > 0 && (
                              <div
                                role="alert"
                                style={{
                                  marginTop: "0.6rem",
                                  padding: "0.6rem 0.7rem",
                                  borderRadius: "6px",
                                  border: "1px solid rgba(251, 191, 36, 0.45)",
                                  background: "rgba(120, 53, 15, 0.22)",
                                }}
                              >
                                <strong>Verify this match</strong>
                                <ul
                                  style={{
                                    margin: "0.35rem 0 0",
                                    paddingLeft: "1.2rem",
                                  }}
                                >
                                  {matchIssues.map((issue) => (
                                    <li key={issue}>{issue}</li>
                                  ))}
                                </ul>
                              </div>
                            )}
                            {possibleMissingSeries.length > 0 && (
                              <p
                                className="hint"
                                style={{ marginTop: "0.5rem" }}
                              >
                                Possible missing in series:{" "}
                                {possibleMissingSeries.join(", ")}
                              </p>
                            )}
                            {evidenceNote && (
                              <details className="workspace-disclosure">
                                <summary>Match explanation</summary>
                                <p className="hint">{evidenceNote}</p>
                              </details>
                            )}
                          </>
                        );
                      })()}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="hint" style={{ marginTop: "0.75rem" }}>
                {inboxLoading
                  ? ""
                  : metadataPage > 0
                    ? "No more suggestions on this page. Go back to the previous page."
                    : "No metadata approvals are waiting right now."}
              </p>
            )}
            <div className="workspace-actions review-pagination">
              <button
                disabled={metadataPage === 0 || inboxLoading}
                onClick={() => setMetadataPage((page) => page - 1)}
              >
                Previous suggestions
              </button>
              <button
                disabled={metadataInbox.length <= 20 || inboxLoading}
                onClick={() => setMetadataPage((page) => page + 1)}
              >
                Next suggestions
              </button>
            </div>
          </section>
        )}

        {activeTab === "audiobooks" && (
          <>
            <section className="settings-section">
              <h3>Rebuild Human Audiobooks</h3>
              <p className="hint">
                Update chapter matches and synchronized text for imported
                audiobooks. Original audio and valid manual chapter corrections
                are kept.
              </p>
              {audiobookRebuildPreviewLoading ? (
                <p className="hint">Inspecting imported audiobooks…</p>
              ) : audiobookRebuildPreviewError ? (
                <p className="error">{audiobookRebuildPreviewError.message}</p>
              ) : audiobookRebuildPreview ? (
                <p className="hint">
                  {audiobookRebuildPreview.rebuild_count} of{" "}
                  {audiobookRebuildPreview.total_count} edition
                  {audiobookRebuildPreview.total_count === 1 ? "" : "s"} need
                  updating
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
                <p className="error">
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
          </>
        )}

        {activeTab === "recycle-bin" && (
          <section className="settings-section">
            <p className="hint">
              Deleted books and all files they own stay recoverable for{" "}
              {recycleBin?.retention_days || 30} days by default. Restore a book
              to return it to the library, or permanently delete it to remove
              its files now.
            </p>
            {recycleBinLoading ? (
              <p className="hint">Loading deleted books…</p>
            ) : (recycleBin?.books || []).length === 0 ? (
              <p className="hint">The recycle bin is empty.</p>
            ) : (
              <ul className="recycle-bin-list">
                {(recycleBin?.books ?? []).map((book) => (
                  <li className="recycle-bin-item" key={book.id}>
                    <div>
                      <strong>{book.title}</strong>
                      <p className="hint">
                        by {book.author || "Unknown author"}
                      </p>
                      <p className="hint">
                        {book.purge_after
                          ? `Recovery window ends ${new Date(book.purge_after).toLocaleString()}`
                          : "No automatic purge date is set"}
                        {!book.recovery_files_available &&
                          " · EPUB recovery file is missing"}
                      </p>
                    </div>
                    <div className="recycle-bin-actions">
                      <button
                        type="button"
                        onClick={() => restoreBookMutation.mutate(book.id)}
                        disabled={
                          restoreBookMutation.isPending ||
                          permanentDeleteMutation.isPending
                        }
                      >
                        Restore
                      </button>
                      <button
                        type="button"
                        className="btn-danger"
                        onClick={() => setPermanentDeleteTarget(book)}
                        disabled={
                          restoreBookMutation.isPending ||
                          permanentDeleteMutation.isPending
                        }
                      >
                        Permanently delete
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {(restoreBookMutation.isError ||
              permanentDeleteMutation.isError) && (
              <p className="error">
                {
                  (restoreBookMutation.error || permanentDeleteMutation.error)
                    ?.message
                }
              </p>
            )}
          </section>
        )}

        {activeTab === "storage" && (
          <section className="settings-section">
            <p className="hint">
              Scans the library directory for orphaned EPUB and cover files, and
              failed web imports that never produced EPUB files. Files owned by
              books in the recycle bin are protected.
            </p>

            <div className="settings-actions">
              {!preview && (
                <button
                  onClick={() => previewMutation.mutate()}
                  disabled={isPending}
                >
                  {previewMutation.isPending
                    ? "Scanning..."
                    : "Scan for Orphaned Files"}
                </button>
              )}

              {preview &&
                preview.dry_run &&
                getCleanupTargetCount(preview) > 0 && (
                  <button
                    className="btn-danger"
                    onClick={() => deleteMutation.mutate()}
                    disabled={isPending}
                  >
                    {deleteMutation.isPending
                      ? "Deleting..."
                      : `Delete ${getCleanupTargetCount(preview)} item${getCleanupTargetCount(preview) !== 1 ? "s" : ""}${preview.total_bytes > 0 ? ` (${formatBytes(preview.total_bytes)})` : ""}`}
                  </button>
                )}

              {preview && (
                <button
                  className="btn-text"
                  onClick={() => {
                    setPreview(null);
                    previewMutation.reset();
                    deleteMutation.reset();
                  }}
                  disabled={isPending}
                >
                  Reset
                </button>
              )}
            </div>

            {(previewMutation.isError || deleteMutation.isError) && (
              <p className="error">
                {(previewMutation.error || deleteMutation.error)?.message}
              </p>
            )}

            {preview?.skipped_reason && (
              <p
                className="hint"
                style={{ marginTop: "0.5rem", color: "#fbbf24" }}
              >
                {preview.skipped_reason}
              </p>
            )}

            {preview && !preview.skipped_reason && (
              <div style={{ marginTop: "1rem" }}>
                <h4>
                  {deleted ? "Deleted Items" : "Cleanup Candidates Found"}
                  <span
                    className="hint"
                    style={{ fontWeight: "normal", marginLeft: "0.5rem" }}
                  >
                    {getCleanupTargetCount(preview) === 0
                      ? "Nothing to remove"
                      : `${formatCleanupSummary(preview)}${preview.total_bytes > 0 ? ` — ${formatBytes(preview.total_bytes)}` : ""}`}
                  </span>
                </h4>

                {getCleanupTargetCount(preview) === 0 ? (
                  <p className="hint">
                    No orphaned files or failed web imports found. Library is
                    clean.
                  </p>
                ) : (
                  <>
                    {getCleanupFiles(preview).length > 0 && (
                      <ul
                        style={{
                          listStyle: "none",
                          padding: 0,
                          margin: 0,
                          display: "flex",
                          flexDirection: "column",
                          gap: "0.25rem",
                        }}
                      >
                        {getCleanupFiles(preview).map((f) => (
                          <li
                            key={f.path}
                            style={{
                              display: "flex",
                              justifyContent: "space-between",
                              alignItems: "center",
                              fontFamily: "monospace",
                              fontSize: "0.8rem",
                              padding: "0.3rem 0.5rem",
                              borderRadius: "4px",
                              background: "var(--surface, #1a1a2e)",
                            }}
                          >
                            <span
                              style={{
                                wordBreak: "break-all",
                                color: deleted ? "#6b7280" : "#e2e8f0",
                              }}
                            >
                              {f.path}
                            </span>
                            <span
                              className="hint"
                              style={{ flexShrink: 0, marginLeft: "1rem" }}
                            >
                              {formatBytes(f.size_bytes)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}

                    {getCleanupBooks(preview).length > 0 && (
                      <ul
                        style={{
                          listStyle: "none",
                          padding: 0,
                          margin:
                            getCleanupFiles(preview).length > 0
                              ? "0.75rem 0 0 0"
                              : 0,
                          display: "flex",
                          flexDirection: "column",
                          gap: "0.35rem",
                        }}
                      >
                        {getCleanupBooks(preview).map((book) => (
                          <li
                            key={book.book_id}
                            style={{
                              display: "flex",
                              justifyContent: "space-between",
                              alignItems: "baseline",
                              fontSize: "0.85rem",
                              padding: "0.4rem 0.6rem",
                              borderRadius: "4px",
                              background: "var(--surface, #1a1a2e)",
                              gap: "1rem",
                            }}
                          >
                            <span style={{ wordBreak: "break-word" }}>
                              <strong>{book.title}</strong>
                              {book.author && (
                                <span className="hint"> by {book.author}</span>
                              )}
                            </span>
                            <span
                              style={{
                                flexShrink: 0,
                                color: "#f87171",
                                fontFamily: "monospace",
                                fontSize: "0.8rem",
                              }}
                            >
                              failed web import
                              {book.source_url && (
                                <span
                                  className="hint"
                                  style={{ marginLeft: "0.5rem" }}
                                >
                                  {book.source_url}
                                </span>
                              )}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                )}

                {deleted && getCleanupTargetCount(preview) > 0 && (
                  <p
                    style={{
                      marginTop: "0.75rem",
                      color: "#4ade80",
                      fontSize: "0.875rem",
                    }}
                  >
                    Deleted {getCleanupTargetCount(preview)} item
                    {getCleanupTargetCount(preview) !== 1 ? "s" : ""}
                    {preview.total_bytes > 0
                      ? `, freed ${formatBytes(preview.total_bytes)}`
                      : ""}
                    .
                  </p>
                )}
              </div>
            )}
          </section>
        )}

        {activeTab === "backups" && <BackupsPanel />}

        {activeTab === "reader-access" && <ReaderKeys showHeading={false} />}
      </div>

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
      <ConfirmActionDialog
        open={Boolean(permanentDeleteTarget)}
        title={`Permanently delete “${permanentDeleteTarget?.title || "this book"}”?`}
        confirmLabel="Permanently delete"
        busyLabel="Deleting…"
        danger
        isPending={permanentDeleteMutation.isPending}
        onCancel={() => setPermanentDeleteTarget(null)}
        onConfirm={() =>
          permanentDeleteTarget &&
          permanentDeleteMutation.mutate(permanentDeleteTarget.id)
        }
      >
        <p>
          This removes the database record, EPUBs, cover, audiobook files, and
          saved revision history.
        </p>
        <p>
          <strong>This cannot be undone.</strong>
        </p>
      </ConfirmActionDialog>
    </div>
  );
}

export default Utilities;
