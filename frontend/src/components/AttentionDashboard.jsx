import {
  BookItem,
  FileItem,
  JobItem,
  MetadataItem,
  AttentionCard,
} from "./attention/AttentionCards";
import useAttentionActions from "./attention/useAttentionActions";
import AttentionAction from "./attention/AttentionAction";

function AttentionDashboard({
  data,
  isLoading,
  error,
  onRefresh,
  isRefreshing,
}) {
  const actions = useAttentionActions(onRefresh);
  const action = (kind, item) => (
    <AttentionAction kind={kind} item={item} actions={actions} />
  );
  const bulk = (kind, items, label) => {
    const eligible = items.filter(
      (item) =>
        item[kind === "cover" ? "can_retry_cover" : "can_retry_refresh"] &&
        !actions.busy(kind, item),
    );
    return items.length > 1 ? (
      <button
        className="attention-bulk-actions"
        disabled={!eligible.length}
        onClick={() => actions.runMany(kind, eligible)}
      >
        {label} ({eligible.length})
      </button>
    ) : null;
  };
  if (isLoading) {
    return <p>Checking library health…</p>;
  }
  if (error) {
    return (
      <div className="attention-page">
        <h2>Needs attention</h2>
        <p className="error" role="alert">
          {error.message}
        </p>
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
          <h2>Needs attention</h2>
          <p>Review failed tasks, missing files, and book suggestions.</p>
        </div>
        <button
          className="btn-text"
          onClick={onRefresh}
          disabled={isRefreshing}
        >
          {isRefreshing ? "Checking…" : "Refresh"}
        </button>
      </header>

      {actions.results.length > 0 && (
        <section aria-label="Recent attention actions">
          {actions.results.map((result) => (
            <p key={result.key} role={result.error ? "alert" : "status"}>
              {result.title}: {result.error || result.message}
            </p>
          ))}
          {actions.pollError && (
            <p role="alert">
              Could not check task progress.{" "}
              <a href="/activity/processing">View processing jobs</a>
            </p>
          )}
        </section>
      )}
      {healthy && (
        <section className="attention-healthy" role="status">
          <strong>Your library looks healthy.</strong>
          <span>Nothing needs your attention.</span>
        </section>
      )}

      <div className="attention-grid">
        <AttentionCard
          title="Failed processing"
          description="Review the error, then retry the task."
          category={data.failed_jobs}
          actionHref="/activity/processing?status=error"
          actionLabel="Review jobs"
        >
          {data.failed_jobs.items.map((item) => (
            <JobItem key={item.id} item={item}>
              {action("job", item)}
            </JobItem>
          ))}
        </AttentionCard>

        <AttentionCard
          title="Failed refreshes"
          description="Web novels that could not be checked for updates."
          category={data.failed_refreshes}
          actionHref="/updates"
          actionLabel="Review web updates"
          bulkAction={bulk(
            "refresh",
            data.failed_refreshes.items,
            "Retry shown checks",
          )}
        >
          {data.failed_refreshes.items.map((item) => (
            <BookItem key={item.book_id} item={item}>
              {item.can_retry_refresh && action("refresh", item)}
            </BookItem>
          ))}
        </AttentionCard>

        <AttentionCard
          title="Audiobooks need updating"
          description="The book text has changed since this audio was created."
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
          description="Book matches waiting for your approval."
          category={data.metadata_proposals}
          actionHref="/review"
          actionLabel="Review metadata"
        >
          {data.metadata_proposals.items.map((item) => (
            <MetadataItem key={item.proposal_id} item={item} />
          ))}
        </AttentionCard>

        <AttentionCard
          title="Broken library files"
          description="Original or cleaned EPUB files that could not be found."
          category={data.broken_files}
          actionHref="/settings/library-tools?section=audit"
          actionLabel="Run audit"
        >
          {data.broken_files.items.map((item, index) => (
            <FileItem
              key={`${item.book_id}-${item.issue}-${index}`}
              item={item}
            />
          ))}
        </AttentionCard>

        <AttentionCard
          title="Missing covers"
          description="Books with missing or unreadable cover images."
          category={data.missing_covers}
          actionHref="/"
          actionLabel="Review library"
          bulkAction={bulk(
            "cover",
            data.missing_covers.items,
            "Recover shown covers",
          )}
        >
          {data.missing_covers.items.map((item) => (
            <FileItem key={`${item.book_id}-${item.issue}`} item={item}>
              {item.can_retry_cover ? (
                action("cover", item)
              ) : (
                <a href={`/books/${item.book_id}/details`}>Choose a cover</a>
              )}
            </FileItem>
          ))}
        </AttentionCard>
      </div>
    </div>
  );
}

export default AttentionDashboard;
