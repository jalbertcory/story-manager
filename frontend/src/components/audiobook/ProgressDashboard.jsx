import { useEffect, useRef, useState } from "react";

const ACTIVE_STATUSES = new Set([
  "ingesting",
  "roster_gen",
  "diarizing",
  "audio_gen",
  "assembling",
]);

function percent(current, total) {
  return total ? Math.round((current * 1000) / total) / 10 : 0;
}

function formatRate(rate) {
  return rate > 0 ? `${rate.toFixed(1)} sentences/min` : "Measuring…";
}

function formatEta(remaining, rate) {
  if (!(rate > 0) || remaining <= 0)
    return remaining <= 0 ? "Complete" : "ETA pending";
  const minutes = remaining / rate;
  if (minutes < 1) return "< 1 min remaining";
  if (minutes < 60) return `~${Math.ceil(minutes)} min remaining`;
  return `~${(minutes / 60).toFixed(1)} hr remaining`;
}

function useProgressRates(analyzed, audio) {
  const samples = useRef([]);
  const [rates, setRates] = useState({ analysis: 0, audio: 0 });

  useEffect(() => {
    const now = Date.now();
    samples.current.push({ now, analyzed, audio });
    samples.current = samples.current.filter(
      (sample) => now - sample.now <= 120_000,
    );
    const baseline = samples.current[0];
    const elapsedMinutes = (now - baseline.now) / 60_000;
    if (elapsedMinutes <= 0) return;
    setRates({
      analysis: Math.max(0, (analyzed - baseline.analyzed) / elapsedMinutes),
      audio: Math.max(0, (audio - baseline.audio) / elapsedMinutes),
    });
  }, [analyzed, audio]);

  return rates;
}

function ProgressMetric({ label, current, total, detail }) {
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

function ProgressDashboard({ status, chapters = [] }) {
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
  const active = ACTIVE_STATUSES.has(status?.pipeline_status);
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
              {status?.pipeline_status || "Not started"}
              {active && (
                <span className="progress-live-pulse" aria-label="working" />
              )}
            </h3>
          </div>
          <span
            className={`badge ${
              status?.pipeline_status === "error"
                ? "badge--error"
                : active
                  ? "badge--success"
                  : "badge--neutral"
            }`}
          >
            {receiving
              ? "Streaming model response"
              : status?.pipeline_status || "idle"}
          </span>
        </div>
        <p className="progress-live-detail">
          {status?.progress_detail || "Waiting for the next pipeline action."}
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
          {status?.pipeline_status === "diarizing" && (
            <span>Analysis and speech lanes are running concurrently</span>
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
          <summary>Most recent recoverable pipeline error</summary>
          <pre>{status.last_error}</pre>
        </details>
      )}

      <section className="progress-chapters">
        <div className="analysis-section-heading">
          <div>
            <span className="metric-label">Per-chapter work</span>
            <h3>Analysis and audio progress</h3>
          </div>
        </div>
        <div className="progress-chapter-list">
          {chapters.map((chapter) => (
            <article className="progress-chapter-row" key={chapter.id}>
              <strong>Chapter {chapter.chapter_number}</strong>
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
