import type { CSSProperties } from "react";
import type { LibraryValues } from "../../types";
import type { getLibraryGroups } from "../../api/library";
import { libraryPath } from "../../lib/library";
import { getApiCoverUrl } from "../../api/covers";

export default function LibraryGroups({
  items,
  groupBy,
  base,
  filters,
}: {
  items: Awaited<ReturnType<typeof getLibraryGroups>>["items"];
  groupBy: string;
  base: LibraryValues;
  filters: LibraryValues;
}) {
  return (
    <div className="library-groups">
      {items.map((item) => (
        <a
          className="library-group-row"
          key={item.name || "ungrouped"}
          href={libraryPath(
            groupBy === "universe"
              ? {
                  group: "universe",
                  universe: item.universe_id || 0,
                  universeName: item.name || "No universe",
                  ...filters,
                }
              : {
                  ...base,
                  series: item.name || "",
                  ...filters,
                },
          )}
        >
          <div className="group-covers">
            {item.cover_ids.length ? (
              item.cover_ids.map((id, i) => (
                <img
                  key={id}
                  src={getApiCoverUrl(id)}
                  alt={
                    i === 0 ? `${item.name || "Standalone books"} cover` : ""
                  }
                  style={{ "--stack-i": i } as CSSProperties}
                  loading="lazy"
                />
              ))
            ) : (
              <span className="cover-placeholder">No cover</span>
            )}
          </div>
          <div>
            <h3>
              {item.name ||
                (groupBy === "universe" ? "No universe" : "Standalone books")}
            </h3>
            <p>
              {item.author_count === 1
                ? item.author
                : `${item.author_count} authors`}
            </p>
            <div className="group-formats">
              <span>
                {item.book_count} {item.book_count === 1 ? "book" : "books"}
              </span>
              {item.audio_count > 0 && (
                <span>{item.audio_count} with audio</span>
              )}
            </div>
          </div>
          <span className="group-chevron" aria-hidden="true">
            ›
          </span>
        </a>
      ))}
      {!items.length && (
        <p className="empty-state">
          No matching groups. Try another search or source.
        </p>
      )}
    </div>
  );
}
