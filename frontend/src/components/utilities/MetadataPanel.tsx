import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveMetadataMatch,
  getLatestMetadataJob,
  getMetadataInbox,
  queueMetadataSync,
  rejectMetadataMatch,
} from "../../api/metadata";
import { displayValue, stringValue } from "../../lib/errors";
import { queryKeys } from "../../lib/queryKeys";

type MetadataEntry = NonNullable<
  Awaited<ReturnType<typeof getMetadataInbox>>[number]["candidate_matches"]
>[number];

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

export default function MetadataPanel() {
  const queryClient = useQueryClient();
  const [metadataPage, setMetadataPage] = useState(0);
  const [selectedMatchIds, setSelectedMatchIds] = useState<
    Record<number, number>
  >({});

  const { data: latestMetadataJob } = useQuery({
    queryKey: queryKeys.metadataJobLatest,
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
    queryKey: queryKeys.metadataInbox.page(metadataPage),
    queryFn: ({ signal }) =>
      getMetadataInbox({ offset: metadataPage * 20, limit: 21 }, { signal }),
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
      void queryClient.invalidateQueries({
        queryKey: queryKeys.metadataJobLatest,
      });
    },
  });

  const approveMatchMutation = useMutation({
    mutationFn: (matchId: number) => approveMetadataMatch(matchId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.bookCatalog.all,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.metadataInbox.all,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.attentionDashboard,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.metadataJobLatest,
      });
    },
  });

  const rejectMatchMutation = useMutation({
    mutationFn: (matchId: number) => rejectMetadataMatch(matchId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.metadataInbox.all,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.attentionDashboard,
      });
    },
  });

  return (
    <section className="settings-section">
      <p className="hint">
        Looks up book details online. Uncertain matches appear below for review.
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
        <p className="error" role="alert" style={{ marginTop: "0.5rem" }}>
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
          {latestMetadataJob ? latestMetadataJob.status : "Not checked yet"}
        </p>
        <p className="hint">{renderMetadataJobSummary(latestMetadataJob)}</p>
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
                                  approveMatchMutation.mutate(selectedMatch.id)
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
                                  rejectMatchMutation.mutate(selectedMatch.id)
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
                      <p className="hint" style={{ marginTop: "0.35rem" }}>
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
                          <p className="hint" style={{ marginTop: "0.5rem" }}>
                            Suggested match:{" "}
                            {formatMetadataMatchOption(selectedMatch)}
                          </p>
                        )
                      )}
                      {(entry.book_series || candidateSeries) && (
                        <p className="hint" style={{ marginTop: "0.5rem" }}>
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
                        <p className="hint" style={{ marginTop: "0.5rem" }}>
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
                        <p className="hint" style={{ marginTop: "0.5rem" }}>
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
  );
}
