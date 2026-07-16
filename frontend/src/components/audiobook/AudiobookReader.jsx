import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getChapterAudioUrl, getSentences } from "../../api/audiobook";

function AudiobookReader({ chapters = [], characters = [], bookId }) {
  const playable = useMemo(
    () =>
      chapters.filter(
        (chapter) => chapter.audio_file_path && !chapter.needs_reassembly,
      ),
    [chapters],
  );
  const [chapterId, setChapterId] = useState(playable[0]?.id ?? null);

  useEffect(() => {
    if (!playable.some((chapter) => chapter.id === chapterId)) {
      setChapterId(playable[0]?.id ?? null);
    }
  }, [chapterId, playable]);

  const selectedIndex = playable.findIndex(
    (chapter) => chapter.id === chapterId,
  );
  const selected = selectedIndex >= 0 ? playable[selectedIndex] : null;
  const { data, isLoading } = useQuery({
    queryKey: ["audiobook-reader-sentences", bookId, chapterId],
    queryFn: () => getSentences(bookId, { chapterId, limit: 1000 }),
    enabled: chapterId != null,
  });
  const characterNames = useMemo(
    () =>
      new Map(characters.map((character) => [character.id, character.name])),
    [characters],
  );

  if (!playable.length) {
    return (
      <p className="empty-state">
        No playable chapters yet. Fully analyze a chapter, then use Generate
        Preview in Chapter Assembly.
      </p>
    );
  }

  return (
    <div className="audiobook-reader">
      <aside
        className="audiobook-reader-chapters"
        aria-label="Playable chapters"
      >
        {playable.map((chapter) => (
          <button
            type="button"
            key={chapter.id}
            className={chapter.id === chapterId ? "active" : ""}
            onClick={() => setChapterId(chapter.id)}
          >
            Chapter {chapter.chapter_number}
            <small>{chapter.sentence_count} sentences</small>
          </button>
        ))}
      </aside>
      <main className="audiobook-reader-content">
        <div className="audiobook-reader-heading">
          <div>
            <span className="metric-label">Listen & read</span>
            <h3>Chapter {selected?.chapter_number}</h3>
          </div>
          <div className="audiobook-reader-nav">
            <button
              type="button"
              disabled={selectedIndex <= 0}
              onClick={() => setChapterId(playable[selectedIndex - 1].id)}
            >
              Previous
            </button>
            <button
              type="button"
              disabled={selectedIndex >= playable.length - 1}
              onClick={() => setChapterId(playable[selectedIndex + 1].id)}
            >
              Next
            </button>
          </div>
        </div>
        <audio
          key={chapterId}
          controls
          src={getChapterAudioUrl(bookId, chapterId)}
          preload="metadata"
          className="audiobook-reader-player"
        />
        {selected?.summary && (
          <p className="audiobook-reader-summary">{selected.summary}</p>
        )}
        {isLoading ? (
          <p>Loading chapter text…</p>
        ) : (
          <div className="audiobook-reader-text">
            {(data?.items || []).map((sentence) => (
              <span
                key={sentence.id}
                title={
                  characterNames.get(sentence.character_id) || "Unassigned"
                }
              >
                {sentence.original_text}{" "}
              </span>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

export default AudiobookReader;
