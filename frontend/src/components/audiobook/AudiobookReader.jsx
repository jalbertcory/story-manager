import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getChapterAudioUrl, getSentences } from "../../api/audiobook";

const PLAYBACK_RATES = [0.75, 1, 1.25, 1.5, 1.75, 2];

function activeSentenceAtTime(timeline, currentTimeSeconds) {
  if (!timeline.length) return null;

  const currentTimeMs = Math.max(0, currentTimeSeconds * 1000);
  return (
    timeline.find(({ endMs }) => currentTimeMs < endMs)?.id ??
    timeline[timeline.length - 1].id
  );
}

function AudiobookReader({ chapters = [], characters = [], bookId }) {
  const playable = useMemo(
    () =>
      chapters.filter(
        (chapter) => chapter.audio_file_path && !chapter.needs_reassembly,
      ),
    [chapters],
  );
  const [chapterId, setChapterId] = useState(playable[0]?.id ?? null);
  const [activeSentenceId, setActiveSentenceId] = useState(null);
  const [playbackRate, setPlaybackRate] = useState(1);
  const audioRef = useRef(null);
  const textRef = useRef(null);
  const sentenceRefs = useRef(new Map());

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
  const sentenceTimeline = useMemo(() => {
    let elapsedMs = 0;
    return (data?.items || []).map((sentence) => {
      const durationMs = Math.max(0, sentence.audio_duration_ms ?? 0);
      elapsedMs += durationMs;
      return { id: sentence.id, endMs: elapsedMs };
    });
  }, [data?.items]);

  useEffect(() => {
    setActiveSentenceId(activeSentenceAtTime(sentenceTimeline, 0));
  }, [chapterId, sentenceTimeline]);

  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.playbackRate = playbackRate;
    }
  }, [chapterId, playbackRate]);

  useEffect(() => {
    if (activeSentenceId == null) return;

    const textElement = textRef.current;
    const sentenceElement = sentenceRefs.current.get(activeSentenceId);
    if (!textElement || !sentenceElement) return;

    const textRect = textElement.getBoundingClientRect();
    const sentenceRect = sentenceElement.getBoundingClientRect();
    const top = sentenceRect.top - textRect.top + textElement.scrollTop;

    if (typeof textElement.scrollTo === "function") {
      textElement.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    }
  }, [activeSentenceId]);

  const syncActiveSentence = (event) => {
    const nextSentenceId = activeSentenceAtTime(
      sentenceTimeline,
      event.currentTarget.currentTime,
    );
    setActiveSentenceId((currentSentenceId) =>
      currentSentenceId === nextSentenceId ? currentSentenceId : nextSentenceId,
    );
  };

  const changePlaybackRate = (event) => {
    const nextRate = Number.parseFloat(event.target.value);
    setPlaybackRate(nextRate);
  };

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
            {chapter.title}
            <small>{chapter.sentence_count} sentences</small>
          </button>
        ))}
      </aside>
      <main className="audiobook-reader-content">
        <div className="audiobook-reader-heading">
          <div>
            <span className="metric-label">Listen & read</span>
            <h3>{selected?.title}</h3>
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
        <div className="audiobook-reader-playback">
          <audio
            key={chapterId}
            ref={audioRef}
            controls
            src={getChapterAudioUrl(bookId, chapterId)}
            preload="metadata"
            className="audiobook-reader-player"
            onLoadedMetadata={(event) => {
              event.currentTarget.playbackRate = playbackRate;
              syncActiveSentence(event);
            }}
            onTimeUpdate={syncActiveSentence}
            onSeeked={syncActiveSentence}
          />
          <label className="audiobook-reader-speed">
            Speed
            <select value={playbackRate} onChange={changePlaybackRate}>
              {PLAYBACK_RATES.map((rate) => (
                <option key={rate} value={rate}>
                  {rate}×
                </option>
              ))}
            </select>
          </label>
        </div>
        {selected?.summary && (
          <p className="audiobook-reader-summary">{selected.summary}</p>
        )}
        {isLoading ? (
          <p>Loading chapter text…</p>
        ) : (
          <div className="audiobook-reader-text" ref={textRef}>
            {(data?.items || []).map((sentence) => (
              <span
                key={sentence.id}
                ref={(element) => {
                  if (element) {
                    sentenceRefs.current.set(sentence.id, element);
                  } else {
                    sentenceRefs.current.delete(sentence.id);
                  }
                }}
                className={`audiobook-reader-sentence${
                  sentence.id === activeSentenceId
                    ? " audiobook-reader-sentence--active"
                    : ""
                }`}
                aria-current={
                  sentence.id === activeSentenceId ? "true" : undefined
                }
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
