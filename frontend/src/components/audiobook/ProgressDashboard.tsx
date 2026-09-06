import type { AudioStatus, Chapter } from "./types";
import { useEffect, useRef, useState } from "react";
import { chapterLabel } from "../../lib/audiobook";
import useLifecycleDefinitions from "../../hooks/useLifecycleDefinitions";

function percent(current: number, total: number) {
  return total ? Math.round((current * 1000) / total) / 10 : 0;
}

function formatRate(rate: number) {
  return rate > 0 ? `${rate.toFixed(1)} sentences/min` : "Measuring…";
}

function formatEta(remaining: number, rate: number) {
  if (!(rate > 0) || remaining <= 0)
    return remaining <= 0 ? "Complete" : "ETA pending";
  const minutes = remaining / rate;
  if (minutes < 1) return "< 1 min remaining";
  if (minutes < 60) return `~${Math.ceil(minutes)} min remaining`;
  return `~${(minutes / 60).toFixed(1)} hr remaining`;
}

function useProgressRates(analyzed: number, audio: number) {
  const samples = useRef<{ now: number; analyzed: number; audio: number }[]>(
    [],
  );
  const [rates, setRates] = useState({ analysis: 0, audio: 0 });

  useEffect(() => {
    const now = Date.now();
    samples.current.push({ now, analyzed, audio });
    samples.current = samples.current.filter(
      (sample) => now - sample.now <= 120_000,
    );
    const baseline = samples.current[0];
    if (!baseline) return;
    const elapsedMinutes = (now - baseline.now) / 60_000;
    if (elapsedMinutes <= 0) return;
    setRates({
      analysis: Math.max(0, (analyzed - baseline.analyzed) / elapsedMinutes),
      audio: Math.max(0, (audio - baseline.audio) / elapsedMinutes),
    });
  }, [analyzed, audio]);

  return rates;
}

function ProgressMetric({
  label,
  current,
  total,
  detail,
}: {
  label: string;
  current: number;
  total: number;
  detail: string;
}) {
  const value = percent(current, total);
  return (
    <article className="progress-metric">
      <div className="progress-metric-heading">
        <span className="metric-label">{label}</span>
        <strong>{value}%</strong>
      </div>
      <progress value={current} max={Math.max(1, total)} />
      <span>
        {current.toLocaleString()} / {total.toLocaleString()} {detail}
      </span>
    </article>
  );
}

function ProgressDashboard({
  status,
  chapters = [],
}: {
  status: AudioStatus | undefined;
  chapters?: Chapter[];
}) {
  const { data: lifecycleDefinitions } = useLifecycleDefinitions();
  const pipelineLifecycle = lifecycleDefinitions?.audiobook_pipeline;
  const stateLabels = Object.fromEntries<string>(
    (pipelineLifecycle?.states ?? []).map((state) => [
      String(state.value),
      state.label,
    ]),
  );
  const activeStatuses = new Set(pipelineLifecycle?.active_states ?? []);
  const failureStatuses = new Set(pipelineLifecycle?.failure_states ?? []);
  const concurrentAnalysisStatuses = new Set(
    pipelineLifecycle?.groups?.concurrent_analysis ?? [],
  );
  const counts = status?.sentence_counts ?? {};
  const totalSentences = Object.values(counts).reduce(
    (sum, count) => sum + count,
    0,
  );
  const pendingAnalysis = counts.pending_diarization ?? 0;
  const analyzedSentences = Math.max(0, totalSentences - pendingAnalysis);
  const generatedAudio = counts.audio_generated ?? 0;
  const failedAudio = counts.error ?? 0;
  const analyzedChapters = chapters.filter(
    (chapter) =>
      chapter.sentence_count > 0 &&
      chapter.processed_sentence_count >= chapter.sentence_count,
  ).length;
  const assembledChapters = chapters.filter(
    (chapter) =>
      chapter.sentence_count > 0 &&
      chapter.audio_generated_count >= chapter.sentence_count &&
      chapter.audio_file_path &&
      chapter.smil_file_path,
  ).length;
  const pipelineStatus = status?.pipeline_status ?? "";
  const pipelineLabel = stateLabels[pipelineStatus] ?? "Not started";
  const active = activeStatuses.has(pipelineStatus);
  const rates = useProgressRates(analyzedSentences, generatedAudio);
  const receiving = status?.progress_detail?.includes("receiving ");
  const startedAt = status?.pipeline_started_at
    ? new Date(status.pipeline_started_at)
    : null;
  const updatedAt = status?.pipeline_updated_at
    ? new Date(status.pipeline_updated_at)
    : null;

  return (
    <div className="progress-dashboard">
      <section className="progress-live-card">
        <div className="progress-live-heading">
          <div>
            <span className="metric-label">Current activity</span>
            <h3>
              {pipelineLabel}
              {active && (
                <span className="progress-live-pulse" aria-label="working" />
              )}
            </h3>
          </div>
          <span
            className={`badge ${
              failureStatuses.has(pipelineStatus)
                ? "badge--error"
                : active
                  ? "badge--success"
                  : "badge--neutral"
            }`}
          >
            {receiving ? "Streaming model response" : pipelineLabel}
          </span>
        </div>
        <p className="progress-live-detail">
          {status?.progress_detail || "Waiting for the next step."}
        </p>
        <div className="progress-live-meta">
          <span>{status?.llm_requests ?? 0} model requests this run</span>
          <span>
            Analysis: {formatRate(rates.analysis)} ·{" "}
            {formatEta(totalSentences - analyzedSentences, rates.analysis)}
          </span>
          <span>
            Audio: {formatRate(rates.audio)} ·{" "}
            {formatEta(totalSentences - generatedAudio, rates.audio)}
          </span>
          {concurrentAnalysisStatuses.has(pipelineStatus) && (
            <span>Analyzing text and generating audio at the same time</span>
          )}
          {startedAt && <span>Started {startedAt.toLocaleString()}</span>}
          {updatedAt && <span>Updated {updatedAt.toLocaleTimeString()}</span>}
        </div>
      </section>

      <section className="progress-metric-grid" aria-label="Pipeline totals">
        <ProgressMetric
          label="Speaker analysis"
          current={analyzedSentences}
          total={totalSentences}
          detail="sentences attributed"
        />
        <ProgressMetric
          label="Speech generation"
          current={generatedAudio}
          total={totalSentences}
          detail="sentence clips ready"
        />
        <ProgressMetric
          label="Chapter analysis"
          current={analyzedChapters}
          total={chapters.length}
          detail="chapters analyzed"
        />
        <ProgressMetric
          label="Chapter assembly"
          current={assembledChapters}
          total={chapters.length}
          detail="chapters assembled"
        />
      </section>

      {failedAudio > 0 && (
        <p className="progress-warning">
          {failedAudio} sentence{failedAudio === 1 ? "" : "s"} currently need an
          audio retry.
        </p>
      )}

      {status?.last_error && (
        <details className="progress-error-detail">
          <summary>Last generation error</summary>
          <pre>{status.last_error}</pre>
        </details>
      )}

      <section className="progress-chapters">
        <div className="analysis-section-heading">
          <div>
            <h3>Analysis and audio progress</h3>
          </div>
        </div>
        <div className="progress-chapter-list">
          {chapters.map((chapter) => (
            <article className="progress-chapter-row" key={chapter.id}>
              <strong>{chapterLabel(chapter)}</strong>
              <div>
                <span>
                  Analysis{" "}
                  {percent(
                    chapter.processed_sentence_count,
                    chapter.sentence_count,
                  )}
                  %
                </span>
                <progress
                  value={chapter.processed_sentence_count}
                  max={Math.max(1, chapter.sentence_count)}
                />
              </div>
              <div>
                <span>
                  Audio{" "}
                  {percent(
                    chapter.audio_generated_count,
                    chapter.sentence_count,
                  )}
                  %
                </span>
                <progress
                  value={chapter.audio_generated_count}
                  max={Math.max(1, chapter.sentence_count)}
                />
              </div>
              <span className="progress-chapter-state">
                {chapter.sentence_count > 0 &&
                chapter.audio_generated_count >= chapter.sentence_count &&
                chapter.audio_file_path &&
                chapter.smil_file_path
                  ? "Assembled"
                  : chapter.audio_generated_count
                    ? "Generating audio"
                    : chapter.sentence_count > 0 &&
                        chapter.processed_sentence_count >=
                          chapter.sentence_count
                      ? "Ready for audio"
                      : chapter.processed_sentence_count
                        ? "Analyzing"
                        : "Waiting"}
              </span>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

export default ProgressDashboard;
