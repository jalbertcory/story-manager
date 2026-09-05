import { useId, useState } from "react";

export default function LibraryToolbar({
  values,
  q,
  setQ,
  change,
  genres = [],
  inSeries,
  filtersOpen,
  onFiltersToggle,
}) {
  const [localOpen, setLocalOpen] = useState(false);
  const expanded = filtersOpen ?? localOpen;
  const panelId = useId();
  const activeCount = [
    values.source,
    values.audiobook,
    values.review,
    values.genre,
  ].filter(Boolean).length;
  const select = (label, key, options) => (
    <label>
      {label}
      <select
        aria-label={`Library ${label.toLowerCase()}`}
        value={values[key] || ""}
        onChange={(event) => change({ [key]: event.target.value || null })}
      >
        {options.map(([value, text]) => (
          <option key={value} value={value}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
  return (
    <div className="library-controls">
      <div className="library-toolbar">
        <input
          aria-label="Search library"
          placeholder="Search title, author, series, universe, or tag"
          value={q}
          onChange={(event) => setQ(event.target.value)}
        />
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={panelId}
          onClick={() => (onFiltersToggle || setLocalOpen)(!expanded)}
        >
          Filters{activeCount > 0 ? ` (${activeCount})` : ""}
        </button>
      </div>
      <div
        id={panelId}
        className="library-toolbar library-filter-panel"
        hidden={!expanded}
      >
        {!inSeries && values.universe == null && (
          <label>
            Group by
            <select
              aria-label="Group library by"
              value={values.group}
              onChange={(event) =>
                change({
                  group: event.target.value,
                  series: null,
                  sort: values.sort === "series_index" ? null : values.sort,
                })
              }
            >
              <option value="series">Series</option>
              <option value="universe">Universe</option>
              <option value="none">None</option>
            </select>
          </label>
        )}
        {select("Source", "source", [
          ["", "All sources"],
          ["epub", "Book files"],
          ["audiobook", "Audio only (missing EPUB)"],
          ["web", "Web novels"],
        ])}
        {select("Audio", "audiobook", [
          ["", "Any audio status"],
          ["playable", "Ready to listen"],
          ["unplayable", "No playable audio"],
          ["available", "Audio imported or enabled"],
          ["none", "No audio imported or enabled"],
        ])}
        {select("Review", "review", [
          ["", "Any review status"],
          ["missing-series", "Missing series"],
          ["refresh-error", "Source check failed"],
          ["refreshing", "Source check in progress"],
        ])}
        {select("Genre", "genre", [
          ["", "All genres"],
          ...(!genres.some((g) => g.name === values.genre) && values.genre
            ? [[values.genre, values.genre]]
            : []),
          ...genres.map((g) => [g.name, `${g.name} (${g.count})`]),
        ])}
        {select("Sort", "sort", [
          ...(inSeries ? [["series_index", "Series order"]] : []),
          ["title", "Title"],
          ["author", "Author"],
          ["word_count", "Word count"],
          ["updated_at", "Last updated"],
        ])}
        {select("Order", "order", [
          ["asc", "Ascending"],
          ["desc", "Descending"],
        ])}
        <button
          onClick={() => {
            setQ("");
            change({
              q: null,
              source: null,
              audiobook: null,
              review: null,
              genre: null,
              sort: null,
              order: null,
            });
          }}
        >
          Clear filters
        </button>
      </div>
    </div>
  );
}
