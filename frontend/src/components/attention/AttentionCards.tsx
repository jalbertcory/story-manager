import type { ReactNode } from "react";
import type { Schemas } from "../../api/client";
import { JOB_LABELS } from "../../lib/processing";

export function BookItem({
  item,
  audiobook = false,
  children,
}: {
  item: Schemas["AttentionBookItem"];
  audiobook?: boolean;
  children?: ReactNode;
}) {
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

export function FileItem({
  item,
  children,
}: {
  item: Schemas["AttentionFileItem"];
  children?: ReactNode;
}) {
  return (
    <li className="attention-item">
      <a href={`/books/${item.book_id}/details`}>{item.title}</a>
      <span>{item.issue.replaceAll("_", " ")}</span>
      {item.path && <small title={item.path}>{item.path}</small>}
      {children}
    </li>
  );
}

export function JobItem({
  item,
  children,
}: {
  item: Schemas["AttentionJobItem"];
  children?: ReactNode;
}) {
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

const formatIndex = (value: number) => `#${value}`;

export function SeriesGapItem({
  item,
  children,
}: {
  item: Schemas["AttentionSeriesGapItem"];
  children?: ReactNode;
}) {
  return (
    <li className="attention-item">
      <strong>{item.series_name}</strong>
      <span>
        Missing {item.missing_indexes.map(formatIndex).join(", ")} · you have{" "}
        {item.owned_count}
      </span>
      {item.possible_titles.length > 0 && (
        <small title={item.possible_titles.join(", ")}>
          Possibly: {item.possible_titles.join(", ")}
        </small>
      )}
      {children}
    </li>
  );
}

function releaseDateLabel(item: Schemas["AttentionReleaseItem"]) {
  const date = item.published_date || item.release_date;
  if (!date) return item.upcoming ? "Upcoming" : "Released";
  return `${item.upcoming ? "Releases" : "Released"} ${date}`;
}

export function ReleaseItem({
  item,
  children,
}: {
  item: Schemas["AttentionReleaseItem"];
  children?: ReactNode;
}) {
  return (
    <li className="attention-item">
      {item.remote_url ? (
        <a href={item.remote_url} target="_blank" rel="noreferrer">
          {item.title}
        </a>
      ) : (
        <strong>{item.title}</strong>
      )}
      <span>{releaseDateLabel(item)}</span>
      <small>
        {item.series_name}
        {item.series_index != null && ` ${formatIndex(item.series_index)}`}
        {item.author && ` · ${item.author}`}
      </small>
      {children}
    </li>
  );
}

export function MetadataItem({
  item,
  children,
}: {
  item: Schemas["AttentionMetadataItem"];
  children?: ReactNode;
}) {
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
}: {
  title: string;
  description: string;
  category: { count: number; items?: unknown[] };
  actionHref?: string;
  actionLabel?: string;
  children: ReactNode;
  bulkAction?: ReactNode;
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
        {hasItems && actionHref && (
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
          {category.count > (category.items?.length || 0) && (
            <small className="attention-more">
              {category.count - (category.items?.length || 0)} more not shown
            </small>
          )}
        </>
      ) : (
        <p className="attention-clear">No attention needed</p>
      )}
    </article>
  );
}
