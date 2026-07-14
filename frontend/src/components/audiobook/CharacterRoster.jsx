import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { rebuildCharacterRoster, updateCharacter } from "../../api/audiobook";

const ACTIVE_STATUSES = new Set([
  "ingesting",
  "roster_gen",
  "diarizing",
  "audio_gen",
  "assembling",
]);

function CharacterCard({ character, bookId }) {
  const queryClient = useQueryClient();
  const [voicePrompt, setVoicePrompt] = useState(
    character.voice_design_prompt || "",
  );
  const [saved, setSaved] = useState(false);

  const mutation = useMutation({
    mutationFn: (data) => updateCharacter(character.id, data),
    onSuccess: () => {
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      queryClient.invalidateQueries({
        queryKey: ["audiobook-characters", bookId],
      });
      queryClient.invalidateQueries({ queryKey: ["audiobook-status", bookId] });
    },
  });

  const handleSave = () => {
    mutation.mutate({ voice_design_prompt: voicePrompt });
  };

  return (
    <div className="character-card">
      <div className="character-card-header">
        <strong>{character.name}</strong>
        {character.is_narrator && <span className="badge">Narrator</span>}
      </div>
      {character.description && (
        <p className="character-description">{character.description}</p>
      )}
      <div className="character-metrics">
        <span>{character.sentence_count ?? 0} assigned sentences</span>
        {character.average_confidence != null && (
          <span>
            {Math.round(character.average_confidence * 100)}% average confidence
          </span>
        )}
      </div>
      {character.aliases?.length > 0 && (
        <p className="character-aliases">
          <strong>Also known as:</strong> {character.aliases.join(", ")}
        </p>
      )}
      {character.evidence?.length > 0 && (
        <details className="character-evidence">
          <summary>
            Identification evidence ({character.evidence.length})
          </summary>
          <ul>
            {character.evidence.map((item, index) => (
              <li key={`${character.id}-evidence-${index}`}>{item}</li>
            ))}
          </ul>
        </details>
      )}
      <label className="character-voice-label">
        Voice Design Prompt
        <input
          type="text"
          value={voicePrompt}
          onChange={(e) => setVoicePrompt(e.target.value)}
          placeholder="e.g. [gender-male][pitch-low][speed-normal]"
        />
      </label>
      <p className="character-voice-hint">
        Tokens: <code>[gender-male|female|neutral]</code>{" "}
        <code>[pitch-low|medium|high]</code>{" "}
        <code>[speed-slow|normal|fast]</code>{" "}
        <code>[age-young|middle|old]</code>{" "}
        <code>[accent-british|american|…]</code>
      </p>
      {mutation.isError && (
        <p className="error">{mutation.error?.message || "Save failed"}</p>
      )}
      {saved && (
        <p className="success">
          Saved — audio for this character will be regenerated.
        </p>
      )}
      <button onClick={handleSave} disabled={mutation.isPending}>
        {mutation.isPending ? "Saving…" : "Save Profile"}
      </button>
    </div>
  );
}

function CharacterRoster({ characters, bookId, pipelineStatus }) {
  const queryClient = useQueryClient();
  const [confirmRegenerate, setConfirmRegenerate] = useState(false);
  const regenerateMutation = useMutation({
    mutationFn: () => rebuildCharacterRoster(bookId),
    onSuccess: () => {
      setConfirmRegenerate(false);
      queryClient.invalidateQueries({ queryKey: ["audiobook-status", bookId] });
      queryClient.invalidateQueries({
        queryKey: ["audiobook-characters", bookId],
      });
      queryClient.invalidateQueries({
        queryKey: ["audiobook-chapters", bookId],
      });
    },
  });

  if (!characters || characters.length === 0) {
    return (
      <p className="empty-state">
        No characters yet. Start the pipeline to generate the roster.
      </p>
    );
  }

  return (
    <>
      <div className="roster-controls">
        <span>
          {characters.length} voice profiles. Regenerating preserves EPUB
          ingestion but clears speaker assignments and invalidates generated
          snippets.
        </span>
        {!confirmRegenerate ? (
          <button
            onClick={() => setConfirmRegenerate(true)}
            disabled={ACTIVE_STATUSES.has(pipelineStatus)}
          >
            Regenerate Character Roster
          </button>
        ) : (
          <span className="confirm-inline">
            Clear existing speaker analysis?{" "}
            <button
              className="btn-danger"
              onClick={() => regenerateMutation.mutate()}
              disabled={regenerateMutation.isPending}
            >
              {regenerateMutation.isPending
                ? "Regenerating…"
                : "Yes, regenerate"}
            </button>{" "}
            <button
              className="btn-text"
              onClick={() => setConfirmRegenerate(false)}
            >
              Cancel
            </button>
          </span>
        )}
        {regenerateMutation.isError && (
          <span className="error">{regenerateMutation.error?.message}</span>
        )}
      </div>
      <div className="character-roster">
        {characters.map((char) => (
          <CharacterCard key={char.id} character={char} bookId={bookId} />
        ))}
      </div>
    </>
  );
}

export default CharacterRoster;
