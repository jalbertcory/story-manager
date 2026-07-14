function AnalysisOverview({ status, chapters = [] }) {
  const analyzed = chapters.filter((chapter) => chapter.summary);

  return (
    <div className="analysis-overview">
      <section className="analysis-book-summary">
        <div className="analysis-section-heading">
          <div>
            <span className="metric-label">Book-level analysis</span>
            <h3>Story summary</h3>
          </div>
          <span className="badge badge--neutral">
            {analyzed.length} / {chapters.length} chapters analyzed
          </span>
        </div>
        <p>
          {status?.summary ||
            "The roster stage will add a spoiler-light book summary here."}
        </p>
        {status?.summary && (
          <small className="analysis-review-note">
            Model-generated working analysis — verify names and plot details before production.
          </small>
        )}
      </section>

      <div className="chapter-analysis-list">
        {chapters.map((chapter) => {
          const percent = chapter.sentence_count
            ? Math.round(
                (chapter.processed_sentence_count * 100) /
                  chapter.sentence_count,
              )
            : 0;
          return (
            <article className="chapter-analysis-card" key={chapter.id}>
              <div className="chapter-analysis-header">
                <strong>Chapter {chapter.chapter_number}</strong>
                <span>{percent}% attributed</span>
              </div>
              <div className="chapter-analysis-counts">
                <span>{chapter.sentence_count} sentences</span>
                <span>{chapter.low_confidence_count} need review</span>
              </div>
              <progress
                value={chapter.processed_sentence_count}
                max={Math.max(1, chapter.sentence_count)}
              />
              <p>
                {chapter.summary ||
                  "No chapter summary yet. Run a diarization batch to analyze it."}
              </p>
            </article>
          );
        })}
      </div>

      {chapters.length === 0 && (
        <p className="empty-state">
          No chapters yet. Run the ingestion stage to inspect book structure.
        </p>
      )}
    </div>
  );
}

export default AnalysisOverview;
