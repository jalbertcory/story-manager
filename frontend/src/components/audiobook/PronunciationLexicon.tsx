import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Schemas } from "../../api/client";
import {
  createPronunciation,
  deletePronunciation,
  getPronunciations,
  previewPronunciation,
  updatePronunciation,
} from "../../api/audiobook";
import { queryKeys } from "../../lib/queryKeys";

type Rule = Schemas["PronunciationResponse"];
type Scope = Rule["scope"];
type Change = Schemas["PronunciationChange"];

function scopeLabel(rule: Rule) {
  if (rule.scope === "book") return "This book";
  if (rule.scope === "series") return `Series: ${rule.series_name ?? ""}`;
  return "Whole library";
}

function changeMessage(action: string, change: Change) {
  if (change.sentences_reset === 0) return `${action}.`;
  const sentences = `${change.sentences_reset.toLocaleString()} recorded sentence${change.sentences_reset === 1 ? "" : "s"}`;
  const books =
    change.books_affected > 1 ? ` across ${change.books_affected} books` : "";
  return `${action}. ${sentences}${books} will be narrated again the next time narration runs.`;
}

function RuleRow({
  rule,
  regenerate,
  onChanged,
  onHear,
  hearing,
}: {
  rule: Rule;
  regenerate: boolean;
  onChanged: (message: string) => void;
  onHear: (text: string) => void;
  hearing: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [term, setTerm] = useState(rule.term);
  const [spoken, setSpoken] = useState(rule.spoken);

  const saveMutation = useMutation({
    mutationFn: () =>
      updatePronunciation(rule.id, { term, spoken, regenerate }),
    onSuccess: (change) => {
      setEditing(false);
      onChanged(changeMessage(`Updated “${term.trim()}”`, change));
    },
  });
  const removeMutation = useMutation({
    mutationFn: () => deletePronunciation(rule.id, regenerate),
    onSuccess: (change) =>
      onChanged(changeMessage(`Removed “${rule.term}”`, change)),
  });
  const error = saveMutation.error ?? removeMutation.error;

  return (
    <tr className={rule.active ? "" : "pronunciation-overridden"}>
      <td>
        {editing ? (
          <input
            aria-label={`Written form of ${rule.term}`}
            value={term}
            onChange={(e) => setTerm(e.target.value)}
          />
        ) : (
          <strong>{rule.term}</strong>
        )}
        {rule.case_sensitive && (
          <span className="badge" title="Only this exact capitalisation">
            Aa
          </span>
        )}
      </td>
      <td>
        {editing ? (
          <input
            aria-label={`Spoken form of ${rule.term}`}
            value={spoken}
            onChange={(e) => setSpoken(e.target.value)}
          />
        ) : (
          rule.spoken
        )}
      </td>
      <td>
        {scopeLabel(rule)}
        {!rule.active && (
          <span className="hint"> · overridden by a closer rule</span>
        )}
      </td>
      <td>{rule.active ? rule.sentence_count.toLocaleString() : "—"}</td>
      <td className="pronunciation-actions">
        <button
          className="btn-text"
          onClick={() => onHear(editing ? spoken : rule.spoken)}
          disabled={hearing}
        >
          Hear
        </button>
        {editing ? (
          <>
            <button
              onClick={() => saveMutation.mutate()}
              disabled={
                saveMutation.isPending || !term.trim() || !spoken.trim()
              }
            >
              {saveMutation.isPending ? "Saving…" : "Save"}
            </button>
            <button
              className="btn-text"
              onClick={() => {
                setTerm(rule.term);
                setSpoken(rule.spoken);
                saveMutation.reset();
                setEditing(false);
              }}
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <button className="btn-text" onClick={() => setEditing(true)}>
              Edit
            </button>
            <button
              className="btn-text"
              aria-label={`Remove ${rule.term}`}
              onClick={() => removeMutation.mutate()}
              disabled={removeMutation.isPending}
            >
              Remove
            </button>
          </>
        )}
        {error && (
          <span className="error" role="alert">
            {error.message}
          </span>
        )}
      </td>
    </tr>
  );
}

function PronunciationLexicon({
  bookId,
  pipelineActive,
}: {
  bookId: number;
  pipelineActive: boolean;
}) {
  const queryClient = useQueryClient();
  const [term, setTerm] = useState("");
  const [spoken, setSpoken] = useState("");
  const [scope, setScope] = useState<Scope>("book");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [regenerateChoice, setRegenerate] = useState(false);
  const [message, setMessage] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  // Recorded sentences cannot be sent back while narration is using them.
  const regenerate = regenerateChoice && !pipelineActive;

  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.audiobook.pronunciations(bookId),
    queryFn: ({ signal }) => getPronunciations(bookId, { signal }),
  });
  const rules = data?.rules ?? [];
  const seriesName = data?.series_name ?? null;

  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );

  const refresh = (text: string) => {
    setMessage(text);
    void queryClient.invalidateQueries({
      queryKey: queryKeys.audiobook.pronunciations(bookId),
    });
    for (const queryKey of [
      queryKeys.audiobook.status(bookId),
      queryKeys.audiobook.chapters(bookId),
      queryKeys.audiobook.sentences.all(bookId),
    ])
      void queryClient.invalidateQueries({ queryKey });
  };

  const addMutation = useMutation({
    mutationFn: () =>
      createPronunciation(bookId, {
        term,
        spoken,
        scope,
        case_sensitive: caseSensitive,
        regenerate,
      }),
    onSuccess: (change) => {
      refresh(changeMessage(`Added “${term.trim()}”`, change));
      setTerm("");
      setSpoken("");
    },
  });

  const hearMutation = useMutation({
    mutationFn: (text: string) => previewPronunciation(bookId, text),
    onSuccess: (audio) => setPreviewUrl(URL.createObjectURL(audio)),
  });

  const handleAdd = (event: FormEvent) => {
    event.preventDefault();
    setMessage("");
    addMutation.mutate();
  };

  return (
    <div className="pronunciation-lexicon">
      <p className="hint">
        Teach the narrator how to say names and invented words. Write the word
        as it appears in the book, then spell out how it should sound, for
        example “Cian” as “KEE-an”. The book’s text and highlighting keep the
        author’s spelling; only the speech changes.
      </p>

      <form className="pronunciation-form" onSubmit={handleAdd}>
        <label>
          Written in the book
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="Cian"
          />
        </label>
        <label>
          Say it as
          <input
            value={spoken}
            onChange={(e) => setSpoken(e.target.value)}
            placeholder="KEE-an"
          />
        </label>
        <label>
          Applies to
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value as Scope)}
          >
            <option value="book">This book</option>
            {seriesName && (
              <option value="series">Every book in {seriesName}</option>
            )}
            <option value="global">Whole library</option>
          </select>
        </label>
        <label className="pronunciation-check">
          <input
            type="checkbox"
            checked={caseSensitive}
            onChange={(e) => setCaseSensitive(e.target.checked)}
          />
          Match capitalisation exactly
        </label>
        <div className="pronunciation-form-actions">
          <button
            type="button"
            onClick={() => hearMutation.mutate(spoken)}
            disabled={hearMutation.isPending || !spoken.trim()}
          >
            {hearMutation.isPending ? "Preparing…" : "Hear it"}
          </button>
          <button
            type="submit"
            className="btn-primary"
            disabled={addMutation.isPending || !term.trim() || !spoken.trim()}
          >
            {addMutation.isPending ? "Adding…" : "Add pronunciation"}
          </button>
        </div>
      </form>

      <label className="pronunciation-check">
        <input
          type="checkbox"
          checked={regenerate}
          disabled={pipelineActive}
          onChange={(e) => setRegenerate(e.target.checked)}
        />
        Narrate already-recorded sentences again when I add, change or remove a
        pronunciation
      </label>
      {pipelineActive && (
        <p className="hint">
          Narration is running, so changes apply to sentences that have not been
          recorded yet. Pause it to redo recorded ones.
        </p>
      )}

      {previewUrl && (
        <audio
          className="pronunciation-preview"
          aria-label="Pronunciation preview"
          controls
          autoPlay
          src={previewUrl}
        />
      )}
      {message && <p className="success">{message}</p>}
      {(addMutation.error ?? hearMutation.error ?? error) && (
        <p className="error" role="alert">
          {(addMutation.error ?? hearMutation.error ?? error)?.message}
        </p>
      )}

      {isPending ? (
        <p className="hint">Loading pronunciations…</p>
      ) : rules.length === 0 ? (
        <p className="hint">No pronunciations yet.</p>
      ) : (
        <div className="pronunciation-table-wrap">
          <table className="pronunciation-table">
            <thead>
              <tr>
                <th>Written</th>
                <th>Spoken</th>
                <th>Applies to</th>
                <th>Sentences here</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <RuleRow
                  key={`${rule.id}-${rule.term}-${rule.spoken}`}
                  rule={rule}
                  regenerate={regenerate}
                  onChanged={refresh}
                  onHear={(text) => hearMutation.mutate(text)}
                  hearing={hearMutation.isPending}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default PronunciationLexicon;
