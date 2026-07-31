import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  getChapterAudioUrl,
  getImportedTrackCues,
  getSentences,
} from "../../api/audiobook";
import { chapterLabel } from "../../lib/audiobook";

function findActiveCue(cues, currentMs) {
  let low = 0;
  let high = cues.length - 1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    const cue = cues[middle];
    if (currentMs < cue.clip_begin_ms) high = middle - 1;
    else if (currentMs >= cue.clip_end_ms) low = middle + 1;
    else return cue;
  }
  return null;
}

function HighlightedText({ cues, activeSentenceId, onSeek }) {
  const activeRef = useRef(null);
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeSentenceId]);
  return (
    <div className="audiobook-reader-text">
      {cues.map((cue) => (
        <span
          key={cue.sentence_id}
          ref={cue.sentence_id === activeSentenceId ? activeRef : null}
          className={
            cue.sentence_id === activeSentenceId
              ? "audiobook-sentence--active"
              : ""
          }
          onClick={() => onSeek(cue.clip_begin_ms)}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              onSeek(cue.clip_begin_ms);
            }
          }}
        >
          {cue.text}{" "}
        </span>
      ))}
    </div>
  );
}

function ImportedEditionReader({ edition }) {
  const playable = edition.tracks.filter((track) => track.cue_count > 0);
  const [trackId, setTrackId] = useState(playable[0]?.id ?? null);
  const [activeSentenceId, setActiveSentenceId] = useState(null);
  const audioRef = useRef(null);

  useEffect(() => {
    if (!playable.some((track) => track.id === trackId)) {
      setTrackId(playable[0]?.id ?? null);
    }
  }, [playable, trackId]);
  const selectedIndex = playable.findIndex((track) => track.id === trackId);
  const selected = selectedIndex >= 0 ? playable[selectedIndex] : null;
  const { data: cues = [], isLoading } = useQuery({
    queryKey: [
      "imported-audiobook-cues",
      edition.id,
      trackId,
      selected?.alignment_score ?? "estimated",
    ],
    queryFn: () => getImportedTrackCues(edition.id, trackId),
    enabled: trackId != null,
  });

  const seek = (timeMs) => {
    if (audioRef.current) {
      audioRef.current.currentTime = timeMs / 1000;
      setActiveSentenceId(findActiveCue(cues, timeMs)?.sentence_id ?? null);
    }
  };
  const startSelectedTrack = () => {
    if (selected) seek(selected.source_start_ms);
  };
  const updateHighlight = (event) => {
    const currentMs = event.currentTarget.currentTime * 1000;
    if (selected && currentMs >= selected.source_end_ms) {
      event.currentTarget.pause();
      event.currentTarget.currentTime = selected.source_end_ms / 1000;
      setActiveSentenceId(cues.at(-1)?.sentence_id ?? null);
      return;
    }
    setActiveSentenceId(findActiveCue(cues, currentMs)?.sentence_id ?? null);
  };

  if (!playable.length) {
    return (
      <p className="empty-state">
        This edition has no tracks matched to book text. Review its track
        matching in Sources.
      </p>
    );
  }
  return (
    <div className="audiobook-reader">
      <aside
        className="audiobook-reader-chapters"
        aria-label="Imported audiobook chapters"
      >
        {playable.map((track) => (
          <button
            type="button"
            key={track.id}
            className={track.id === trackId ? "active" : ""}
            onClick={() => setTrackId(track.id)}
          >
            {track.title}
            <small>{track.cue_count} synchronized passages</small>
          </button>
        ))}
      </aside>
      <main className="audiobook-reader-content">
        <div className="audiobook-reader-heading">
          <div>
            <span className="metric-label">
              Listen & read · human narration
            </span>
            <h3>{selected?.title}</h3>
          </div>
          <div className="audiobook-reader-nav">
            <button
              type="button"
              disabled={selectedIndex <= 0}
              onClick={() => setTrackId(playable[selectedIndex - 1].id)}
            >
              Previous
            </button>
            <button
              type="button"
              disabled={selectedIndex >= playable.length - 1}
              onClick={() => setTrackId(playable[selectedIndex + 1].id)}
            >
              Next
            </button>
          </div>
        </div>
        <audio
          ref={audioRef}
          key={trackId}
          controls
          src={selected?.audio_url}
          preload="metadata"
          className="audiobook-reader-player"
          onLoadedMetadata={startSelectedTrack}
          onPlay={(event) => {
            if (
              selected &&
              (event.currentTarget.currentTime * 1000 <
                selected.source_start_ms ||
                event.currentTarget.currentTime * 1000 >=
                  selected.source_end_ms)
            ) {
              startSelectedTrack();
            }
          }}
          onTimeUpdate={updateHighlight}
          onSeeked={updateHighlight}
        />
        <p className="audiobook-reader-summary">
          Click any sentence to seek.{" "}
          {selected?.alignment_score == null
            ? "Estimated highlighting can drift within a chapter; CUE chapter boundaries remain exact."
            : `Whisper-aligned timing · ${Math.round(selected.alignment_score * 100)}% text match confidence.`}
        </p>
        {isLoading ? (
          <p>Loading synchronized text…</p>
        ) : (
          <HighlightedText
            cues={cues}
            activeSentenceId={activeSentenceId}
            onSeek={seek}
          />
        )}
      </main>
    </div>
  );
}

function GeneratedEditionReader({ chapters, characters, bookId }) {
  const playable = useMemo(
    () =>
      chapters.filter(
        (chapter) => chapter.audio_file_path && !chapter.needs_reassembly,
      ),
    [chapters],
  );
  const [chapterId, setChapterId] = useState(playable[0]?.id ?? null);
  const [activeSentenceId, setActiveSentenceId] = useState(null);
  const audioRef = useRef(null);

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
  const cues = useMemo(() => {
    let currentMs = 0;
    return (data?.items || []).map((sentence) => {
      const begin = currentMs;
      currentMs += sentence.audio_duration_ms || 0;
      return {
        sentence_id: sentence.id,
        text: sentence.original_text,
        clip_begin_ms: begin,
        clip_end_ms: currentMs,
      };
    });
  }, [data]);
  const characterNames = useMemo(
    () =>
      new Map(characters.map((character) => [character.id, character.name])),
    [characters],
  );
  const seek = (timeMs) => {
    if (audioRef.current) audioRef.current.currentTime = timeMs / 1000;
  };

  if (!playable.length) {
    return (
      <p className="empty-state">
        No generated chapters are playable yet. Fully analyze a chapter, then
        use Generate Preview in Chapter Assembly.
      </p>
    );
  }

  return (
    <div className="audiobook-reader">
      <aside
        className="audiobook-reader-chapters"
        aria-label="Generated audiobook chapters"
      >
        {playable.map((chapter) => (
          <button
            type="button"
            key={chapter.id}
            className={chapter.id === chapterId ? "active" : ""}
            onClick={() => setChapterId(chapter.id)}
          >
            {chapterLabel(chapter)}
            <small>{chapter.sentence_count} sentences</small>
          </button>
        ))}
      </aside>
      <main className="audiobook-reader-content">
        <div className="audiobook-reader-heading">
          <div>
            <span className="metric-label">Listen & read · AI narration</span>
            <h3>{chapterLabel(selected)}</h3>
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
          ref={audioRef}
          key={chapterId}
          controls
          src={getChapterAudioUrl(bookId, chapterId)}
          preload="metadata"
          className="audiobook-reader-player"
          onTimeUpdate={(event) =>
            setActiveSentenceId(
              findActiveCue(cues, event.currentTarget.currentTime * 1000)
                ?.sentence_id ?? null,
            )
          }
        />
        {selected?.summary && (
          <p className="audiobook-reader-summary">{selected.summary}</p>
        )}
        {isLoading ? (
          <p>Loading chapter text…</p>
        ) : (
          <div className="audiobook-reader-text">
            {cues.map((cue) => {
              const sentence = data.items.find(
                (item) => item.id === cue.sentence_id,
              );
              return (
                <span
                  key={cue.sentence_id}
                  title={
                    characterNames.get(sentence?.character_id) || "Unassigned"
                  }
                  className={
                    cue.sentence_id === activeSentenceId
                      ? "audiobook-sentence--active"
                      : ""
                  }
                  onClick={() => seek(cue.clip_begin_ms)}
                >
                  {cue.text}{" "}
                </span>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}

function AudiobookReader({
  chapters = [],
  characters = [],
  bookId,
  imports = [],
  aiEnabled = false,
}) {
  const generatedPlayable = chapters.some(
    (chapter) => chapter.audio_file_path && !chapter.needs_reassembly,
  );
  const importedEditions = useMemo(
    () =>
      imports.filter(
        (edition) =>
          ["ready", "aligning"].includes(edition.status) &&
          edition.tracks.some((track) => track.cue_count > 0),
      ),
    [imports],
  );
  const sources = useMemo(
    () => [
      ...(generatedPlayable && aiEnabled
        ? [{ key: "generated", label: "AI-generated edition" }]
        : []),
      ...importedEditions.map((edition) => ({
        key: `import-${edition.id}`,
        label: edition.name,
      })),
    ],
    [aiEnabled, generatedPlayable, importedEditions],
  );
  const [sourceKey, setSourceKey] = useState(sources[0]?.key ?? "");

  useEffect(() => {
    if (!sources.some((source) => source.key === sourceKey)) {
      setSourceKey(sources[0]?.key ?? "");
    }
  }, [sourceKey, sources]);

  if (!sources.length) {
    return (
      <p className="empty-state">
        No playable audiobook edition yet. Import human narration in Sources or
        generate an AI chapter preview.
      </p>
    );
  }
  const imported = sourceKey.startsWith("import-")
    ? importedEditions.find((edition) => `import-${edition.id}` === sourceKey)
    : null;
  return (
    <div className="audiobook-edition-reader">
      <label className="audiobook-edition-select">
        Audiobook edition
        <select
          value={sourceKey}
          onChange={(event) => setSourceKey(event.target.value)}
        >
          {sources.map((source) => (
            <option key={source.key} value={source.key}>
              {source.label}
            </option>
          ))}
        </select>
      </label>
      {imported ? (
        <ImportedEditionReader edition={imported} />
      ) : (
        <GeneratedEditionReader
          chapters={chapters}
          characters={characters}
          bookId={bookId}
        />
      )}
    </div>
  );
}

export default AudiobookReader;
