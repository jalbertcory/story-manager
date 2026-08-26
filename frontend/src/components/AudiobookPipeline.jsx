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
  getImportedAudiobooks,
} from "../api/audiobook";
import CharacterRoster from "./audiobook/CharacterRoster";
import ScriptEditor from "./audiobook/ScriptEditor";
import ChapterAssembly from "./audiobook/ChapterAssembly";
import AnalysisOverview from "./audiobook/AnalysisOverview";
import AudiobookReader from "./audiobook/AudiobookReader";
import ProgressDashboard from "./audiobook/ProgressDashboard";
import AudiobookSources from "./audiobook/AudiobookSources";
import { AUDIOBOOK_TABS } from "../lib/navigation";
import useLifecycleDefinitions from "../hooks/useLifecycleDefinitions";

function PipelineProgress({ status, steps }) {
  const currentIdx = steps.findIndex((step) => step.status === status);
  return (
    <div className="pipeline-progress">
      {steps.map((step, idx) => {
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

const AI_SUB_TAB_KEYS = new Set([
  "progress",
  "analysis",
  "characters",
  "script-editor",
  "chapter-assembly",
]);

function AudiobookPipeline({
  book,
  onEnableAi,
  audiobookTab,
  onAudiobookTabChange,
}) {
  const { data: lifecycleDefinitions } = useLifecycleDefinitions();
  const pipelineLifecycle = lifecycleDefinitions?.audiobook_pipeline;
  const importedLifecycle = lifecycleDefinitions?.imported_audiobook;
  const previewLifecycle = lifecycleDefinitions?.chapter_preview;
  const sentenceLifecycle = lifecycleDefinitions?.sentence;
  const stateLabels = Object.fromEntries(
    (pipelineLifecycle?.states ?? []).map((state) => [
      state.value,
      state.label,
    ]),
  );
  const pipelineSteps = (pipelineLifecycle?.groups?.progress_steps ?? []).map(
    (status) => ({
      status,
      label: stateLabels[status] ?? status,
    }),
  );
  const activeStatuses = new Set(pipelineLifecycle?.active_states ?? []);
  const batchableStatuses = new Set(pipelineLifecycle?.groups?.batchable ?? []);
  const failedPipelineStatuses = new Set(
    pipelineLifecycle?.failure_states ?? [],
  );
  const readyPipelineStatuses = new Set(pipelineLifecycle?.groups?.ready ?? []);
  const pausedPipelineStatuses = new Set(
    pipelineLifecycle?.groups?.paused ?? [],
  );
  const activeImportStatuses = new Set(importedLifecycle?.active_states ?? []);
  const activePreviewStatuses = new Set(previewLifecycle?.active_states ?? []);
  const playableSentenceStatuses =
    sentenceLifecycle?.groups?.audio_playable ?? [];
  const bookId = book.id;
  const aiEnabled = book.audiobook_enabled !== false;
  const queryClient = useQueryClient();
  const [internalSubTab, setInternalSubTab] = useState(
    book.audiobook_enabled === undefined ? "progress" : "sources",
  );
  const [confirmRebuild, setConfirmRebuild] = useState(false);
  const [lastQueuedJob, setLastQueuedJob] = useState(null);

  const isActive = (status) => activeStatuses.has(status);

  const { data: statusData } = useQuery({
    queryKey: ["audiobook-status", bookId],
    queryFn: () => getAudiobookStatus(bookId),
    enabled: aiEnabled,
    refetchInterval: ({ state }) => {
      const s = state.data?.pipeline_status;
      const audioStillFinishing =
        (state.data?.sentence_counts?.audio_generating ?? 0) > 0;
      return (s && isActive(s)) || audioStillFinishing ? 1000 : false;
    },
  });

  const { data: characters = [] } = useQuery({
    queryKey: ["audiobook-characters", bookId],
    queryFn: () => getCharacters(bookId),
    enabled: aiEnabled,
  });

  const { data: imports = [] } = useQuery({
    queryKey: ["audiobook-imports", bookId],
    queryFn: () => getImportedAudiobooks(bookId),
    refetchInterval: ({ state }) =>
      Array.isArray(state.data) &&
      state.data.some((edition) => activeImportStatuses.has(edition.status))
        ? 1000
        : false,
  });
  const importedAudiobooks = Array.isArray(imports) ? imports : [];

  const { data: chapters = [] } = useQuery({
    queryKey: ["audiobook-chapters", bookId],
    queryFn: () => getAudiobookChapters(bookId),
    refetchInterval: ({ state }) => {
      const s = statusData?.pipeline_status;
      const previewActive = state.data?.some((chapter) =>
        activePreviewStatuses.has(chapter.preview_status),
      );
      const audioStillFinishing =
        (statusData?.sentence_counts?.audio_generating ?? 0) > 0;
      return (s && isActive(s)) || previewActive || audioStillFinishing
        ? 1000
        : false;
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
    onSuccess: (data) => {
      setLastQueuedJob(data.processing_job_id || true);
      invalidateAll();
    },
  });

  const stepMutation = useMutation({
    mutationFn: () => stepPipeline(bookId),
    onSuccess: (data) => {
      setLastQueuedJob(data.processing_job_id || true);
      invalidateAll();
    },
  });

  const batchMutation = useMutation({
    mutationFn: () => runPipelineBatch(bookId),
    onSuccess: (data) => {
      setLastQueuedJob(data.processing_job_id || true);
      invalidateAll();
    },
  });

  const pauseMutation = useMutation({
    mutationFn: () => pausePipeline(bookId),
    onSuccess: invalidateAll,
  });

  const rebuildMutation = useMutation({
    mutationFn: () => rebuildPipeline(bookId),
    onSuccess: (data) => {
      setLastQueuedJob(data.processing_job_id || true);
      setConfirmRebuild(false);
      invalidateAll();
    },
  });

  const pipelineStatus = statusData?.pipeline_status ?? null;
  const nextPhase = statusData?.next_phase ?? "ingesting";
  const pauseRequested = statusData?.pause_requested ?? false;
  const progressStatus =
    isActive(pipelineStatus) || readyPipelineStatuses.has(pipelineStatus)
      ? pipelineStatus
      : nextPhase;
  const nextPhaseLabel =
    pipelineSteps.find((step) => step.status === nextPhase)?.label ?? nextPhase;
  const sentenceCounts = statusData?.sentence_counts ?? {};
  const totalSentences = Object.values(sentenceCounts).reduce(
    (a, b) => a + b,
    0,
  );
  const doneCount = playableSentenceStatuses.reduce(
    (count, status) => count + (sentenceCounts[status] ?? 0),
    0,
  );

  // A fast local/stub phase can finish before the slower data queries poll.
  // Refresh editor data whenever the durable pipeline state advances so the
  // review screen always reflects the checkpoint that was just reached.
  useEffect(() => {
    if (aiEnabled && pipelineStatus !== undefined) {
      queryClient.invalidateQueries({
        queryKey: ["audiobook-characters", bookId],
      });
      queryClient.invalidateQueries({
        queryKey: ["audiobook-chapters", bookId],
      });
    }
  }, [aiEnabled, bookId, pipelineStatus, queryClient]);

  const subTabs = AUDIOBOOK_TABS.filter(
    (tab) => !AI_SUB_TAB_KEYS.has(tab.key) || aiEnabled,
  );
  const requestedSubTab = audiobookTab || internalSubTab;
  const subTab = subTabs.some((tab) => tab.key === requestedSubTab)
    ? requestedSubTab
    : "sources";
  const selectSubTab = (tab) => {
    setInternalSubTab(tab);
    onAudiobookTabChange?.(tab);
  };

  return (
    <div className="audiobook-pipeline">
      {aiEnabled && (
        <div className="pipeline-header">
          <PipelineProgress status={progressStatus} steps={pipelineSteps} />

          <div className="pipeline-meta">
            {totalSentences > 0 && (
              <span className="pipeline-sentence-count">
                {doneCount} / {totalSentences} sentences with audio
              </span>
            )}
            {failedPipelineStatuses.has(pipelineStatus) && (
              <span className="badge badge--error">Pipeline error</span>
            )}
            {pausedPipelineStatuses.has(pipelineStatus) && (
              <span className="badge badge--warning">
                Paused — next: {nextPhaseLabel}
              </span>
            )}
            {pauseRequested && (
              <span className="badge badge--warning">Pause requested…</span>
            )}
            {statusData?.last_error && (
              <details className="pipeline-error-summary">
                <summary>Last pipeline error</summary>
                <pre>{statusData.last_error}</pre>
              </details>
            )}
          </div>

          <JobInspector
            statusData={statusData}
            totalSentences={totalSentences}
            doneCount={doneCount}
          />

          <div className="pipeline-controls">
            {readyPipelineStatuses.has(pipelineStatus) && (
              <a
                className="btn btn-primary"
                href={getAudiobookDownloadUrl(bookId)}
                download
              >
                Download Audiobook EPUB
              </a>
            )}
            {!readyPipelineStatuses.has(pipelineStatus) &&
              !isActive(pipelineStatus) && (
                <>
                  {batchableStatuses.has(nextPhase) && (
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
            {!isActive(pipelineStatus) &&
              (!confirmRebuild ? (
                <button
                  className="btn-danger"
                  onClick={() => setConfirmRebuild(true)}
                >
                  Rebuild AI Audiobook
                </button>
              ) : (
                <span className="confirm-inline">
                  Rebuild the AI roster, speaker assignments, TTS, and assembly?
                  Imported human audiobooks and alignments will be preserved.{" "}
                  <button
                    className="btn-danger"
                    onClick={() => rebuildMutation.mutate()}
                    disabled={rebuildMutation.isPending}
                  >
                    {rebuildMutation.isPending
                      ? "Queueing…"
                      : "Yes, queue rebuild"}
                  </button>{" "}
                  <button
                    className="btn-text"
                    onClick={() => setConfirmRebuild(false)}
                  >
                    Cancel
                  </button>
                </span>
              ))}
          </div>

          {lastQueuedJob && (
            <p className="job-queued-notice" role="status">
              Processing job
              {typeof lastQueuedJob === "number"
                ? ` #${lastQueuedJob}`
                : ""}{" "}
              queued. <a href="/processing">View processing</a>
            </p>
          )}

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
      )}

      <nav className="sub-tabs">
        {subTabs.map((tab) => (
          <button
            key={tab.key}
            className={`sub-tab${subTab === tab.key ? " sub-tab--active" : ""}`}
            onClick={() => selectSubTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <div className="sub-tab-content">
        {subTab === "sources" && (
          <AudiobookSources
            bookId={bookId}
            chapters={chapters}
            imports={importedAudiobooks}
            aiEnabled={aiEnabled}
            aiPipelineActive={isActive(pipelineStatus)}
            onEnableAi={onEnableAi}
          />
        )}
        {subTab === "progress" && (
          <ProgressDashboard status={statusData} chapters={chapters} />
        )}
        {subTab === "analysis" && (
          <AnalysisOverview status={statusData} chapters={chapters} />
        )}
        {subTab === "characters" && (
          <CharacterRoster
            characters={characters}
            bookId={bookId}
            pipelineStatus={pipelineStatus}
            series={book.series}
            ttsProvider={statusData?.tts_provider}
            ttsProviderLocked={statusData?.tts_provider_locked}
            availableTtsProviders={statusData?.available_tts_providers || []}
          />
        )}
        {subTab === "script-editor" && (
          <ScriptEditor
            bookId={bookId}
            characters={characters}
            chapters={chapters}
            pipelineActive={isActive(pipelineStatus)}
          />
        )}
        {subTab === "chapter-assembly" && (
          <ChapterAssembly
            chapters={chapters}
            bookId={bookId}
            pipelineActive={isActive(pipelineStatus)}
          />
        )}
        {subTab === "listen-read" && (
          <AudiobookReader
            chapters={chapters}
            characters={characters}
            bookId={bookId}
            imports={importedAudiobooks}
            aiEnabled={aiEnabled}
          />
        )}
      </div>
    </div>
  );
}

export default AudiobookPipeline;
