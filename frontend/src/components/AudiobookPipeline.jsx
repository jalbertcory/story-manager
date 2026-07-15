import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getAudiobookStatus,
  getCharacters,
  getAudiobookChapters,
  startPipeline,
  stepPipeline,
  runPipelineBatch,
  pausePipeline,
  rebuildPipeline,
  getAudiobookDownloadUrl,
} from "../api/audiobook";
import CharacterRoster from "./audiobook/CharacterRoster";
import ScriptEditor from "./audiobook/ScriptEditor";
import ChapterAssembly from "./audiobook/ChapterAssembly";
import AnalysisOverview from "./audiobook/AnalysisOverview";
import AudiobookReader from "./audiobook/AudiobookReader";

const PIPELINE_STEPS = [
  { status: "ingesting", label: "Ingesting" },
  { status: "roster_gen", label: "Roster" },
  { status: "diarizing", label: "Diarizing" },
  { status: "audio_gen", label: "TTS" },
  { status: "assembling", label: "Assembly" },
  { status: "complete", label: "Complete" },
];

const ACTIVE_STATUSES = new Set([
  "ingesting",
  "roster_gen",
  "diarizing",
  "audio_gen",
  "assembling",
]);
const BATCHABLE_STATUSES = new Set(["diarizing", "audio_gen", "assembling"]);

function PipelineProgress({ status }) {
  const currentIdx = PIPELINE_STEPS.findIndex((s) => s.status === status);
  return (
    <div className="pipeline-progress">
      {PIPELINE_STEPS.map((step, idx) => {
        let cls = "pipeline-step";
        if (idx < currentIdx) cls += " pipeline-step--done";
        else if (idx === currentIdx) cls += " pipeline-step--active";
        return (
          <div key={step.status} className={cls}>
            <div className="pipeline-step-dot" />
            <span>{step.label}</span>
          </div>
        );
      })}
    </div>
  );
}

function JobInspector({ statusData, totalSentences, doneCount }) {
  const progressTotal = statusData?.progress_total ?? 0;
  const progressCurrent = statusData?.progress_current ?? 0;
  const percent = statusData?.progress_percent ?? 0;
  const review = statusData?.review_counts ?? {};

  return (
    <section className="pipeline-inspector" aria-label="Audiobook job details">
      <div className="pipeline-inspector-grid">
        <div>
          <span className="metric-label">Active model</span>
          <strong>
            {statusData?.llm_provider || "stub"}
            {statusData?.llm_model ? ` / ${statusData.llm_model}` : ""}
          </strong>
        </div>
        <div>
          <span className="metric-label">Model requests</span>
          <strong>{statusData?.llm_requests ?? 0}</strong>
        </div>
        <div>
          <span className="metric-label">Sentence state</span>
          <strong>
            {doneCount} audio / {totalSentences} total
          </strong>
        </div>
        <div>
          <span className="metric-label">Needs review</span>
          <strong>
            {review.low_confidence ?? 0} low confidence ·{" "}
            {review.unassigned ?? 0} unassigned
          </strong>
        </div>
      </div>
      {progressTotal > 0 && (
        <div className="pipeline-work-progress">
          <div className="pipeline-work-progress-label">
            <span>{statusData?.progress_detail || "Working…"}</span>
            <strong>
              {progressCurrent.toLocaleString()} /{" "}
              {progressTotal.toLocaleString()} ({percent}%)
            </strong>
          </div>
          <progress value={progressCurrent} max={progressTotal} />
        </div>
      )}
      {statusData?.summary && (
        <details className="pipeline-summary" open>
          <summary>Model analysis summary · review required</summary>
          <p>{statusData.summary}</p>
        </details>
      )}
    </section>
  );
}

const SUB_TABS = [
  "Analysis",
  "Characters",
  "Script Editor",
  "Listen & Read",
  "Chapter Assembly",
];

function AudiobookPipeline({ book }) {
  const bookId = book.id;
  const queryClient = useQueryClient();
  const [subTab, setSubTab] = useState("Analysis");
  const [confirmRebuild, setConfirmRebuild] = useState(false);

  const isActive = (status) => ACTIVE_STATUSES.has(status);

  const { data: statusData } = useQuery({
    queryKey: ["audiobook-status", bookId],
    queryFn: () => getAudiobookStatus(bookId),
    refetchInterval: ({ state }) => {
      const s = state.data?.pipeline_status;
      return s && isActive(s) ? 3000 : false;
    },
  });

  const { data: characters = [] } = useQuery({
    queryKey: ["audiobook-characters", bookId],
    queryFn: () => getCharacters(bookId),
  });

  const { data: chapters = [] } = useQuery({
    queryKey: ["audiobook-chapters", bookId],
    queryFn: () => getAudiobookChapters(bookId),
    refetchInterval: ({ state }) => {
      const s = statusData?.pipeline_status;
      const previewActive = state.data?.some((chapter) =>
        ["queued", "generating"].includes(chapter.preview_status),
      );
      return (s && isActive(s)) || previewActive ? 3000 : false;
    },
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["audiobook-status", bookId] });
    queryClient.invalidateQueries({
      queryKey: ["audiobook-characters", bookId],
    });
    queryClient.invalidateQueries({ queryKey: ["audiobook-chapters", bookId] });
  };

  const startMutation = useMutation({
    mutationFn: () => startPipeline(bookId),
    onSuccess: invalidateAll,
  });

  const stepMutation = useMutation({
    mutationFn: () => stepPipeline(bookId),
    onSuccess: invalidateAll,
  });

  const batchMutation = useMutation({
    mutationFn: () => runPipelineBatch(bookId),
    onSuccess: invalidateAll,
  });

  const pauseMutation = useMutation({
    mutationFn: () => pausePipeline(bookId),
    onSuccess: invalidateAll,
  });

  const rebuildMutation = useMutation({
    mutationFn: () => rebuildPipeline(bookId),
    onSuccess: () => {
      setConfirmRebuild(false);
      invalidateAll();
    },
  });

  const pipelineStatus = statusData?.pipeline_status ?? null;
  const nextPhase = statusData?.next_phase ?? "ingesting";
  const pauseRequested = statusData?.pause_requested ?? false;
  const progressStatus =
    isActive(pipelineStatus) || pipelineStatus === "complete"
      ? pipelineStatus
      : nextPhase;
  const nextPhaseLabel =
    PIPELINE_STEPS.find((step) => step.status === nextPhase)?.label ??
    nextPhase;
  const sentenceCounts = statusData?.sentence_counts ?? {};
  const totalSentences = Object.values(sentenceCounts).reduce(
    (a, b) => a + b,
    0,
  );
  const doneCount = sentenceCounts["audio_generated"] ?? 0;

  // A fast local/stub phase can finish before the slower data queries poll.
  // Refresh editor data whenever the durable pipeline state advances so the
  // review screen always reflects the checkpoint that was just reached.
  useEffect(() => {
    if (pipelineStatus !== undefined) {
      queryClient.invalidateQueries({
        queryKey: ["audiobook-characters", bookId],
      });
      queryClient.invalidateQueries({
        queryKey: ["audiobook-chapters", bookId],
      });
    }
  }, [bookId, pipelineStatus, queryClient]);

  return (
    <div className="audiobook-pipeline">
      <div className="pipeline-header">
        <PipelineProgress status={progressStatus} />

        <div className="pipeline-meta">
          {totalSentences > 0 && (
            <span className="pipeline-sentence-count">
              {doneCount} / {totalSentences} sentences with audio
            </span>
          )}
          {pipelineStatus === "error" && (
            <span className="badge badge--error">Pipeline error</span>
          )}
          {pipelineStatus === "paused" && (
            <span className="badge badge--warning">
              Paused — next: {nextPhaseLabel}
            </span>
          )}
          {pauseRequested && (
            <span className="badge badge--warning">Pause requested…</span>
          )}
          {statusData?.last_error && (
            <p className="error">{statusData.last_error}</p>
          )}
        </div>

        <JobInspector
          statusData={statusData}
          totalSentences={totalSentences}
          doneCount={doneCount}
        />

        <div className="pipeline-controls">
          {pipelineStatus === "complete" && (
            <a
              className="btn btn-primary"
              href={getAudiobookDownloadUrl(bookId)}
              download
            >
              Download Audiobook EPUB
            </a>
          )}
          {pipelineStatus !== "complete" && !isActive(pipelineStatus) && (
            <>
              {BATCHABLE_STATUSES.has(nextPhase) && (
                <button
                  onClick={() => batchMutation.mutate()}
                  disabled={
                    batchMutation.isPending ||
                    stepMutation.isPending ||
                    startMutation.isPending
                  }
                >
                  {batchMutation.isPending
                    ? "Starting Batch…"
                    : "Run One Batch"}
                </button>
              )}
              <button
                onClick={() => stepMutation.mutate()}
                disabled={
                  stepMutation.isPending ||
                  startMutation.isPending ||
                  batchMutation.isPending
                }
              >
                Run Next Stage: {nextPhaseLabel}
              </button>
              <button
                onClick={() => startMutation.mutate()}
                disabled={
                  startMutation.isPending ||
                  stepMutation.isPending ||
                  batchMutation.isPending
                }
                className="btn-primary"
              >
                Run to Completion
              </button>
            </>
          )}
          {isActive(pipelineStatus) && (
            <button
              onClick={() => pauseMutation.mutate()}
              disabled={pauseMutation.isPending || pauseRequested}
            >
              {pauseRequested ? "Pause Requested…" : "Pause Safely"}
            </button>
          )}
          {!confirmRebuild ? (
            <button
              className="btn-danger"
              onClick={() => setConfirmRebuild(true)}
            >
              Force Full Rebuild
            </button>
          ) : (
            <span className="confirm-inline">
              Destroy all audio and re-run from scratch?{" "}
              <button
                className="btn-danger"
                onClick={() => rebuildMutation.mutate()}
                disabled={rebuildMutation.isPending}
              >
                {rebuildMutation.isPending ? "Rebuilding…" : "Yes, rebuild"}
              </button>{" "}
              <button
                className="btn-text"
                onClick={() => setConfirmRebuild(false)}
              >
                Cancel
              </button>
            </span>
          )}
        </div>

        {(startMutation.isError ||
          stepMutation.isError ||
          batchMutation.isError ||
          pauseMutation.isError ||
          rebuildMutation.isError) && (
          <p className="error">
            {(
              startMutation.error ||
              stepMutation.error ||
              batchMutation.error ||
              pauseMutation.error ||
              rebuildMutation.error
            )?.message || "Action failed"}
          </p>
        )}
      </div>

      <nav className="sub-tabs">
        {SUB_TABS.map((t) => (
          <button
            key={t}
            className={`sub-tab${subTab === t ? " sub-tab--active" : ""}`}
            onClick={() => setSubTab(t)}
          >
            {t}
          </button>
        ))}
      </nav>

      <div className="sub-tab-content">
        {subTab === "Analysis" && (
          <AnalysisOverview status={statusData} chapters={chapters} />
        )}
        {subTab === "Characters" && (
          <CharacterRoster
            characters={characters}
            bookId={bookId}
            pipelineStatus={pipelineStatus}
            series={book.series}
          />
        )}
        {subTab === "Script Editor" && (
          <ScriptEditor
            bookId={bookId}
            characters={characters}
            chapters={chapters}
            pipelineActive={isActive(pipelineStatus)}
          />
        )}
        {subTab === "Chapter Assembly" && (
          <ChapterAssembly
            chapters={chapters}
            bookId={bookId}
            pipelineActive={isActive(pipelineStatus)}
          />
        )}
        {subTab === "Listen & Read" && (
          <AudiobookReader
            chapters={chapters}
            characters={characters}
            bookId={bookId}
          />
        )}
      </div>
    </div>
  );
}

export default AudiobookPipeline;
