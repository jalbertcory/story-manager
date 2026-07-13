import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getAudiobookStatus,
  getCharacters,
  getAudiobookChapters,
  startPipeline,
  pausePipeline,
  rebuildPipeline,
  getAudiobookDownloadUrl,
} from "../api/audiobook";
import CharacterRoster from "./audiobook/CharacterRoster";
import ScriptEditor from "./audiobook/ScriptEditor";
import ChapterAssembly from "./audiobook/ChapterAssembly";

const PIPELINE_STEPS = [
  { status: "ingesting", label: "Ingesting" },
  { status: "roster_gen", label: "Roster" },
  { status: "diarizing", label: "Diarizing" },
  { status: "audio_gen", label: "TTS" },
  { status: "assembling", label: "Assembly" },
  { status: "complete", label: "Complete" },
];

const ACTIVE_STATUSES = new Set(["ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"]);

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

const SUB_TABS = ["Characters", "Script Editor", "Chapter Assembly"];

function AudiobookPipeline({ book }) {
  const bookId = book.id;
  const queryClient = useQueryClient();
  const [subTab, setSubTab] = useState("Characters");
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
    refetchInterval: () => {
      const s = statusData?.pipeline_status;
      return s && isActive(s) ? 5000 : false;
    },
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["audiobook-status", bookId] });
    queryClient.invalidateQueries({ queryKey: ["audiobook-characters", bookId] });
    queryClient.invalidateQueries({ queryKey: ["audiobook-chapters", bookId] });
  };

  const startMutation = useMutation({
    mutationFn: () => startPipeline(bookId),
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
  const sentenceCounts = statusData?.sentence_counts ?? {};
  const totalSentences = Object.values(sentenceCounts).reduce((a, b) => a + b, 0);
  const doneCount = sentenceCounts["audio_generated"] ?? 0;

  return (
    <div className="audiobook-pipeline">
      <div className="pipeline-header">
        <PipelineProgress status={pipelineStatus} />

        <div className="pipeline-meta">
          {totalSentences > 0 && (
            <span className="pipeline-sentence-count">
              {doneCount} / {totalSentences} sentences with audio
            </span>
          )}
          {pipelineStatus === "error" && (
            <span className="badge badge--error">Pipeline error — check logs</span>
          )}
          {pipelineStatus === "paused" && (
            <span className="badge badge--warning">Paused</span>
          )}
        </div>

        <div className="pipeline-controls">
          {pipelineStatus === "complete" && (
            <a className="btn btn-primary" href={getAudiobookDownloadUrl(bookId)} download>
              Download Audiobook EPUB
            </a>
          )}
          {pipelineStatus !== "complete" && !isActive(pipelineStatus) && (
            <button
              onClick={() => startMutation.mutate()}
              disabled={startMutation.isPending}
              className="btn-primary"
            >
              {pipelineStatus ? "Resume Pipeline" : "Start Pipeline"}
            </button>
          )}
          {isActive(pipelineStatus) && (
            <button
              onClick={() => pauseMutation.mutate()}
              disabled={pauseMutation.isPending}
            >
              Pause Workers
            </button>
          )}
          {!confirmRebuild ? (
            <button className="btn-danger" onClick={() => setConfirmRebuild(true)}>
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
              <button className="btn-text" onClick={() => setConfirmRebuild(false)}>
                Cancel
              </button>
            </span>
          )}
        </div>

        {(startMutation.isError || pauseMutation.isError || rebuildMutation.isError) && (
          <p className="error">
            {(startMutation.error || pauseMutation.error || rebuildMutation.error)?.message ||
              "Action failed"}
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
        {subTab === "Characters" && (
          <CharacterRoster characters={characters} bookId={bookId} />
        )}
        {subTab === "Script Editor" && (
          <ScriptEditor bookId={bookId} characters={characters} />
        )}
        {subTab === "Chapter Assembly" && (
          <ChapterAssembly chapters={chapters} bookId={bookId} />
        )}
      </div>
    </div>
  );
}

export default AudiobookPipeline;
