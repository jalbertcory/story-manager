import type { SyntheticEvent } from "react";
import type { Chapter, Character, ImportedEdition, ReadingCue } from "./types";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  getChapterAudioUrl,
  getImportedTrackCues,
  getSentences,
} from "../../api/audiobook";
import { chapterLabel } from "../../lib/audiobook";

function findActiveCue(cues: ReadingCue[], currentMs: number) {
  let low = 0;
  let high = cues.length - 1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    const cue = cues[middle];
    if (!cue) return null;
    if (currentMs < cue.clip_begin_ms) high = middle - 1;
    else if (currentMs >= cue.clip_end_ms) low = middle + 1;
    else return cue;
  }
  return null;
}

function groupCuesByReadingBlock(cues: ReadingCue[]) {
  const blocks: {
    key: string;
    unstructured: boolean;
    type: string;
    cues: ReadingCue[];
  }[] = [];
  for (const cue of cues) {
    const previous = blocks.at(-1);
    const unstructured = cue.reading_block_index == null;
    const key = unstructured
      ? `unstructured-${blocks.length}`
      : `block-${cue.reading_block_index}`;
    if (
      previous &&
      ((unstructured && previous.unstructured) ||
        (!unstructured && previous.key === key))
    ) {
      previous.cues.push(cue);
    } else {
      blocks.push({
        key,
        unstructured,
        type: cue.reading_block_type || "paragraph",
        cues: [cue],
      });
    }
  }
  return blocks;
}

function HighlightedText({
  cues,
  activeSentenceId,
  onSeek,
  titleForCue = () => undefined,
}: {
  cues: ReadingCue[];
  activeSentenceId: number | null;
  onSeek: (time: number) => void;
  titleForCue?: (cue: ReadingCue) => string | undefined;
}) {
  const activeRef = useRef<HTMLSpanElement>(null);
  const blocks = useMemo(() => groupCuesByReadingBlock(cues), [cues]);
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeSentenceId]);
  return (
    <div className="audiobook-reader-text">
      {blocks.map((block) => {
        const BlockTag =
          block.type === "heading"
            ? "h4"
            : block.type === "quote"
              ? "blockquote"
              : "p";
        return (
          <BlockTag
            key={block.key}
            className={`audiobook-reader-block audiobook-reader-block--${block.type}`}
          >
            {block.cues.map((cue) => (
              <span
                key={cue.sentence_id}
                ref={cue.sentence_id === activeSentenceId ? activeRef : null}
                title={titleForCue(cue)}
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
          </BlockTag>
        );
      })}
    </div>
  );
}

function ImportedEditionReader({
  edition,
  audioOnly = false,
}: {
  edition: ImportedEdition;
  audioOnly?: boolean;
}) {
  const playable = edition.tracks.filter(
    (track) => audioOnly || track.cue_count > 0,
  );
  const [trackId, setTrackId] = useState(playable[0]?.id ?? null);
  const [activeSentenceId, setActiveSentenceId] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

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
    queryFn: () =>
      trackId == null
        ? Promise.resolve([])
        : getImportedTrackCues(edition.id, trackId),
    enabled: trackId != null && !audioOnly,
  });

  const seek = (timeMs: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = timeMs / 1000;
      setActiveSentenceId(findActiveCue(cues, timeMs)?.sentence_id ?? null);
    }
  };
  const startSelectedTrack = () => {
    if (selected) seek(selected.source_start_ms);
  };
  const updateHighlight = (event: SyntheticEvent<HTMLAudioElement>) => {
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
        This edition's imported audio is intact, but it has no synchronized book
        text. Use Rematch to Book Text in Sources to restore it.
      </p>
    );
  }
  return (
    <div className="audiobook-reader">
      <label className="audiobook-chapter-picker">
        Chapter
        <select
          value={trackId ?? ""}
          onChange={(event) => setTrackId(Number(event.target.value))}
        >
          {playable.map((track) => (
            <option key={track.id} value={track.id}>
              {track.title}
            </option>
          ))}
        </select>
      </label>
      <aside
        className="audiobook-reader-chapters"
        aria-label="Imported audiobook chapters"
      >
        {playable.map((track) => (
          <button
            type="button"
            key={track.id}
            className={track.id === trackId ? "active" : ""}
            aria-current={track.id === trackId ? "true" : undefined}
            onClick={() => setTrackId(track.id)}
          >
            {track.title}
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
              onClick={() => {
                const target = playable[selectedIndex - 1];
                if (target) setTrackId(target.id);
              }}
            >
              Previous
            </button>
            <button
              type="button"
              disabled={selectedIndex >= playable.length - 1}
              onClick={() => {
                const target = playable[selectedIndex + 1];
                if (target) setTrackId(target.id);
              }}
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
        {!audioOnly && (
          <>
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
          </>
        )}
      </main>
    </div>
  );
}

function GeneratedEditionReader({
  chapters,
  characters,
  bookId,
}: {
  chapters: Chapter[];
  characters: Character[];
  bookId: number;
}) {
  const playable = useMemo(
    () =>
      chapters.filter(
        (chapter) => chapter.audio_file_path && !chapter.needs_reassembly,
      ),
    [chapters],
  );
  const [chapterId, setChapterId] = useState(playable[0]?.id ?? null);
  const [activeSentenceId, setActiveSentenceId] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

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
    queryFn: () => {
      if (chapterId == null) throw new Error("Choose a chapter first.");
      return getSentences(bookId, { chapterId, limit: 1000 });
    },
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
        reading_block_index: sentence.reading_block_index,
        reading_block_type: sentence.reading_block_type,
      };
    });
  }, [data]);
  const characterNames = useMemo(
    () =>
      new Map(characters.map((character) => [character.id, character.name])),
    [characters],
  );
  const seek = (timeMs: number) => {
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
      <label className="audiobook-chapter-picker">
        Chapter
        <select
          value={chapterId ?? ""}
          onChange={(event) => setChapterId(Number(event.target.value))}
        >
          {playable.map((chapter) => (
            <option key={chapter.id} value={chapter.id}>
              {chapterLabel(chapter)}
            </option>
          ))}
        </select>
      </label>
      <aside
        className="audiobook-reader-chapters"
        aria-label="Generated audiobook chapters"
      >
        {playable.map((chapter) => (
          <button
            type="button"
            key={chapter.id}
            className={chapter.id === chapterId ? "active" : ""}
            aria-current={chapter.id === chapterId ? "true" : undefined}
            onClick={() => setChapterId(chapter.id)}
          >
            {chapterLabel(chapter)}
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
              onClick={() => {
                const target = playable[selectedIndex - 1];
                if (target) setChapterId(target.id);
              }}
            >
              Previous
            </button>
            <button
              type="button"
              disabled={selectedIndex >= playable.length - 1}
              onClick={() => {
                const target = playable[selectedIndex + 1];
                if (target) setChapterId(target.id);
              }}
            >
              Next
            </button>
          </div>
        </div>
        <audio
          ref={audioRef}
          key={chapterId}
          controls
          src={
            chapterId == null
              ? undefined
              : getChapterAudioUrl(bookId, chapterId)
          }
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
          <HighlightedText
            cues={cues}
            activeSentenceId={activeSentenceId}
            onSeek={seek}
            titleForCue={(cue) => {
              const sentence = data?.items.find(
                (item) => item.id === cue.sentence_id,
              );
              return (
                characterNames.get(sentence?.character_id ?? -1) || "Unassigned"
              );
            }}
          />
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
  audioOnly = false,
}: {
  chapters?: Chapter[];
  characters?: Character[];
  bookId: number;
  imports?: ImportedEdition[];
  aiEnabled?: boolean;
  audioOnly?: boolean;
}) {
  const generatedPlayable = chapters.some(
    (chapter) => chapter.audio_file_path && !chapter.needs_reassembly,
  );
  const importedEditions = useMemo(
    () =>
      imports.filter(
        (edition) =>
          ["ready", "aligning"].includes(edition.status) &&
          edition.tracks.length > 0,
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
        <ImportedEditionReader edition={imported} audioOnly={audioOnly} />
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
