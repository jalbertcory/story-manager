import { JOB_LABELS } from "../../lib/processing";

export function BookItem({ item, audiobook = false, children }) {
  const href = audiobook
    ? `/books/${item.book_id}/audiobooks?tab=sources`
    : `/books/${item.book_id}/details`;
  return (
    <li className="attention-item">
      <a href={href}>{item.title}</a>
      <span>{item.author || "Unknown author"}</span>
      {item.detail && <small>{item.detail}</small>}
      {children}
    </li>
  );
}

export function FileItem({ item, children }) {
  return (
    <li className="attention-item">
      <a href={`/books/${item.book_id}/details`}>{item.title}</a>
      <span>{item.issue.replaceAll("_", " ")}</span>
      {item.path && <small title={item.path}>{item.path}</small>}
      {children}
    </li>
  );
}

export function JobItem({ item, children }) {
  return (
    <li className="attention-item">
      <strong>
        {JOB_LABELS[item.job_type] || item.job_type.replaceAll("_", " ")}
      </strong>
      {item.book_id ? (
        <a href={`/books/${item.book_id}/details`}>
          {item.book_title || `Book ${item.book_id}`}
        </a>
      ) : (
        <span>Library operation</span>
      )}
      {item.error && (
        <small className="attention-item-error">{item.error}</small>
      )}
      {children}
    </li>
  );
}

export function MetadataItem({ item, children }) {
  return (
    <li className="attention-item">
      <a href={`/books/${item.book_id}/details`}>{item.title}</a>
      <span>{item.author || "Unknown author"}</span>
      {item.note && <small>{item.note}</small>}
      {children}
    </li>
  );
}

export function AttentionCard({
  title,
  description,
  category,
  actionHref,
  actionLabel,
  children,
  bulkAction,
}) {
  const hasItems = category.count > 0;
  return (
    <article
      className={`attention-card${hasItems ? " attention-card--open" : ""}`}
    >
      <header className="attention-card-header">
        <div>
          <span
            className="attention-count"
            aria-label={`${category.count} ${title.toLowerCase()}`}
          >
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
          {bulkAction}
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
