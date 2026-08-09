const JOB_LABELS = {
  clean_book: "Clean book",
  clean_all: "Clean library",
  refresh_book: "Refresh book",
  refresh_all: "Refresh web library",
  audiobook_pipeline: "Generate AI audiobook",
  import_audiobook: "Import human audiobook",
  rematch_imported_audiobook: "Rematch human audiobook",
  align_imported_audiobook: "Align human audiobook",
  metadata_sync: "Sync metadata",
  generate_sentence_audio: "Generate sentence audio",
  generate_chapter_preview: "Generate chapter preview",
  retry_cover: "Re-extract book cover",
};

function BookItem({ item, audiobook = false }) {
  const href = audiobook
    ? `/books/${item.book_id}/audiobooks?tab=sources`
    : `/books/${item.book_id}/details`;
  return (
    <li className="attention-item">
      <a href={href}>{item.title}</a>
      <span>{item.author || "Unknown author"}</span>
      {item.detail && <small>{item.detail}</small>}
    </li>
  );
}

function FileItem({ item }) {
  return (
    <li className="attention-item">
      <a href={`/books/${item.book_id}/details`}>{item.title}</a>
      <span>{item.issue.replaceAll("_", " ")}</span>
      {item.path && <small title={item.path}>{item.path}</small>}
    </li>
  );
}

function JobItem({ item }) {
  return (
    <li className="attention-item">
      <strong>{JOB_LABELS[item.job_type] || item.job_type.replaceAll("_", " ")}</strong>
      {item.book_id ? (
        <a href={`/books/${item.book_id}/details`}>
          {item.book_title || `Book ${item.book_id}`}
        </a>
      ) : (
        <span>Library operation</span>
      )}
      {item.error && <small className="attention-item-error">{item.error}</small>}
    </li>
  );
}

function MetadataItem({ item }) {
  return (
    <li className="attention-item">
      <a href={`/books/${item.book_id}/details`}>{item.title}</a>
      <span>{item.author || "Unknown author"}</span>
      {item.note && <small>{item.note}</small>}
    </li>
  );
}

function AttentionCard({ title, description, category, actionHref, actionLabel, children }) {
  const hasItems = category.count > 0;
  return (
    <article className={`attention-card${hasItems ? " attention-card--open" : ""}`}>
      <header className="attention-card-header">
        <div>
          <span className="attention-count" aria-label={`${category.count} ${title.toLowerCase()}`}>
            {category.count}
          </span>
          <h3>{title}</h3>
        </div>
        {hasItems && (
          <a className="btn btn-sm" href={actionHref}>
            {actionLabel}
          </a>
        )}
      </header>
      <p>{description}</p>
      {hasItems ? (
        <>
          <ul className="attention-list">{children}</ul>
          {category.count > category.items.length && (
            <small className="attention-more">
              {category.count - category.items.length} more not shown
            </small>
          )}
        </>
      ) : (
        <p className="attention-clear">No attention needed</p>
      )}
    </article>
  );
}

function AttentionDashboard({ data, isLoading, error, onRefresh, isRefreshing }) {
  if (isLoading) {
    return <p>Checking library health…</p>;
  }
  if (error) {
    return (
      <div className="attention-page">
        <h2>Needs attention</h2>
        <p className="error" role="alert">{error.message}</p>
        <button onClick={onRefresh}>Try again</button>
      </div>
    );
  }
  if (!data) return null;

  const healthy = data.total_count === 0;
  return (
    <div className="attention-page">
      <header className="attention-page-header">
        <div>
          <span className="attention-eyebrow">LIBRARY OVERVIEW</span>
          <h2>Needs attention</h2>
          <p>
            Problems and pending decisions that may keep books, updates, or audiobooks from being ready.
          </p>
        </div>
        <button className="btn-text" onClick={onRefresh} disabled={isRefreshing}>
          {isRefreshing ? "Checking…" : "Refresh"}
        </button>
      </header>

      {healthy && (
        <section className="attention-healthy" role="status">
          <strong>Your library looks healthy.</strong>
          <span>No failed work, stale audio, pending metadata, or missing files were found.</span>
        </section>
      )}

      <div className="attention-grid">
        <AttentionCard
          title="Failed processing"
          description="Durable jobs that stopped before completing. Retry them after reviewing the error."
          category={data.failed_jobs}
          actionHref="/activity/processing?status=error"
          actionLabel="Review jobs"
        >
          {data.failed_jobs.items.map((item) => <JobItem key={item.id} item={item} />)}
        </AttentionCard>

        <AttentionCard
          title="Failed refreshes"
          description="Web books whose latest source refresh did not complete."
          category={data.failed_refreshes}
          actionHref="/#web"
          actionLabel="View web books"
        >
          {data.failed_refreshes.items.map((item) => <BookItem key={item.book_id} item={item} />)}
        </AttentionCard>

        <AttentionCard
          title="Stale audiobooks"
          description="Audio that no longer matches the current cleaned book text."
          category={data.stale_audiobooks}
          actionHref="/activity/processing"
          actionLabel="View processing"
        >
          {data.stale_audiobooks.items.map((item) => (
            <BookItem key={item.book_id} item={item} audiobook />
          ))}
        </AttentionCard>

        <AttentionCard
          title="Metadata decisions"
          description="Matches or proposed metadata waiting for approval or dismissal."
          category={data.metadata_proposals}
          actionHref="/settings/library-tools?section=metadata"
          actionLabel="Review metadata"
        >
          {data.metadata_proposals.items.map((item) => (
            <MetadataItem key={item.proposal_id} item={item} />
          ))}
        </AttentionCard>

        <AttentionCard
          title="Broken library files"
          description="Book records whose original or current EPUB file cannot be found."
          category={data.broken_files}
          actionHref="/settings/library-tools?section=audit"
          actionLabel="Run audit"
        >
          {data.broken_files.items.map((item, index) => (
            <FileItem key={`${item.book_id}-${item.issue}-${index}`} item={item} />
          ))}
        </AttentionCard>

        <AttentionCard
          title="Missing covers"
          description="Completed books with no usable local cover image."
          category={data.missing_covers}
          actionHref="/settings/library-tools?section=audit"
          actionLabel="Review library"
        >
          {data.missing_covers.items.map((item) => (
            <FileItem key={`${item.book_id}-${item.issue}`} item={item} />
          ))}
        </AttentionCard>
      </div>
    </div>
  );
}

export default AttentionDashboard;
