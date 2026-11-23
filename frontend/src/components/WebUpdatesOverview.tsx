import { useQuery } from "@tanstack/react-query";
import { getApiCoverUrl } from "../api/covers";
import { getWebUpdates } from "../api/library";
import {
  chaptersAdded,
  dayLabel,
  RECENT_UPDATE_DAYS,
  updatesByDay,
} from "../lib/library";
import { buildBookPath } from "../lib/navigation";
import { queryKeys } from "../lib/queryKeys";

// How far back the feed reaches; matches the endpoint's default window.
const FEED_DAYS = 30;

const plural = (count: number, one: string, many: string) =>
  `${count.toLocaleString()} ${count === 1 ? one : many}`;

// Everything that arrived lately, across every followed story, in one place.
export default function WebUpdatesOverview() {
  const updates = useQuery({
    queryKey: queryKeys.webUpdateEvents,
    queryFn: getWebUpdates,
    refetchInterval: 30000,
  });
  const events = updates.data || [];
  const recent = events.filter(
    (event) =>
      Date.now() - new Date(event.timestamp).getTime() <
      RECENT_UPDATE_DAYS * 86400000,
  );
  const stats = [
    [new Set(recent.map((event) => event.book_id)).size, "stories updated"],
    [
      recent.reduce((sum, event) => sum + event.chapters_added, 0),
      "new chapters",
    ],
    [recent.reduce((sum, event) => sum + event.words_added, 0), "words added"],
  ] as const;
  const days = updatesByDay(events);
  return (
    <div className="updates-overview">
      {updates.error && (
        <p className="error" role="alert">
          {updates.error.message}
        </p>
      )}
      {updates.isLoading && <p role="status">Loading recent updates…</p>}
      {updates.data && (
        <>
          <div className="updates-stats">
            {stats.map(([value, label]) => (
              <p key={label}>
                <strong>{value.toLocaleString()}</strong>
                {label}
              </p>
            ))}
            <p className="hint">in the last {RECENT_UPDATE_DAYS} days</p>
          </div>
          {days.map((day) => (
            <section className="updates-day" key={day.date.getTime()}>
              <h3>
                {dayLabel(day.date)}
                <span>
                  {plural(day.stories.length, "story", "stories")}
                  {day.chapters > 0 &&
                    ` · ${plural(day.chapters, "new chapter", "new chapters")}`}
                </span>
              </h3>
              <ul>
                {day.stories.map((story) => (
                  <li key={story.book_id}>
                    <a href={buildBookPath(story.book_id, "overview")}>
                      <span className="updates-cover">
                        {story.has_cover && (
                          <img
                            src={getApiCoverUrl(story.book_id)}
                            alt=""
                            loading="lazy"
                            decoding="async"
                          />
                        )}
                      </span>
                      <span className="updates-story">
                        <strong>{story.title}</strong>
                        <span>{story.author || "Unknown author"}</span>
                      </span>
                      <span className="updates-marker">
                        {chaptersAdded(story.chapters_added)}
                      </span>
                      <span className="updates-detail">
                        {story.words_added > 0 &&
                          `${story.words_added.toLocaleString()} words · `}
                        {new Date(story.timestamp).toLocaleTimeString([], {
                          hour: "numeric",
                          minute: "2-digit",
                        })}
                      </span>
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          ))}
          {!days.length && (
            <p className="empty-state">
              No new chapters in the last {FEED_DAYS} days.
            </p>
          )}
        </>
      )}
    </div>
  );
}
