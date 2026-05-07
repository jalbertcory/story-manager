import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getSentences, updateSentence, getSentenceAudioUrl } from "../../api/audiobook";

const STATUS_ICONS = {
  pending_diarization: { icon: "⏳", label: "Pending diarization" },
  ready_for_audio: { icon: "🎙", label: "Ready for audio" },
  audio_generated: { icon: "✅", label: "Audio generated" },
  error: { icon: "❌", label: "Error" },
};

function SentenceRow({ sentence, characters, bookId }) {
  const queryClient = useQueryClient();
  const [tags, setTags] = useState(sentence.tagged_text || sentence.original_text);
  const [characterId, setCharacterId] = useState(sentence.character_id ?? "");
  const [editing, setEditing] = useState(false);

  const mutation = useMutation({
    mutationFn: (data) => updateSentence(sentence.id, data),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["audiobook-sentences", bookId] });
      queryClient.invalidateQueries({ queryKey: ["audiobook-status", bookId] });
    },
  });

  const handleSave = () => {
    mutation.mutate({
      character_id: characterId !== "" ? Number(characterId) : null,
      tagged_text: tags,
    });
  };

  const statusInfo = STATUS_ICONS[sentence.status] || { icon: "?", label: sentence.status };
  const audioUrl = sentence.status === "audio_generated" ? getSentenceAudioUrl(sentence.id) : null;

  return (
    <tr className={`sentence-row sentence-row--${sentence.status}`}>
      <td className="sentence-seq">{sentence.sequence_order}</td>
      <td className="sentence-text">{sentence.original_text}</td>
      <td className="sentence-tags">
        {editing ? (
          <input
            type="text"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            className="sentence-tags-input"
          />
        ) : (
          <span onClick={() => setEditing(true)} title="Click to edit">
            {tags}
          </span>
        )}
      </td>
      <td className="sentence-speaker">
        <select
          value={characterId}
          onChange={(e) => {
            setCharacterId(e.target.value);
            setEditing(true);
          }}
        >
          <option value="">— unassigned —</option>
          {characters.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </td>
      <td className="sentence-status" title={statusInfo.label}>
        {statusInfo.icon}
      </td>
      <td className="sentence-audio">
        {audioUrl && (
          <audio controls src={audioUrl} preload="none" style={{ height: "24px" }} />
        )}
      </td>
      <td className="sentence-actions">
        {editing && (
          <>
            <button onClick={handleSave} disabled={mutation.isPending} className="btn-small">
              {mutation.isPending ? "…" : "Save"}
            </button>
            <button
              onClick={() => {
                setTags(sentence.tagged_text || sentence.original_text);
                setCharacterId(sentence.character_id ?? "");
                setEditing(false);
              }}
              className="btn-small btn-text"
            >
              Cancel
            </button>
          </>
        )}
        {mutation.isError && <span className="error">{mutation.error?.message}</span>}
      </td>
    </tr>
  );
}

function ScriptEditor({ bookId, characters }) {
  const [page, setPage] = useState(1);
  const [chapterFilter, _setChapterFilter] = useState("");
  const limit = 50;

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["audiobook-sentences", bookId, page, chapterFilter],
    queryFn: () =>
      getSentences(bookId, {
        page,
        limit,
        chapterId: chapterFilter ? Number(chapterFilter) : undefined,
      }),
    keepPreviousData: true,
  });

  if (isLoading) return <p>Loading sentences…</p>;
  if (isError) return <p className="error">{error?.message || "Failed to load sentences"}</p>;

  const { items = [], total = 0 } = data || {};
  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="script-editor">
      <div className="script-editor-controls">
        <span>{total} sentences</span>
        <div className="pagination">
          <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
            ‹ Prev
          </button>
          <span>
            Page {page} / {totalPages}
          </span>
          <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}>
            Next ›
          </button>
        </div>
      </div>

      {items.length === 0 ? (
        <p className="empty-state">No sentences found. Start the pipeline first.</p>
      ) : (
        <div className="script-table-wrap">
          <table className="script-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Original Text</th>
                <th>Tags</th>
                <th>Speaker</th>
                <th>Status</th>
                <th>Audio</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((sentence) => (
                <SentenceRow
                  key={sentence.id}
                  sentence={sentence}
                  characters={characters}
                  bookId={bookId}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default ScriptEditor;
