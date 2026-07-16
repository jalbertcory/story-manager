import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { updateCharacter } from "../../api/audiobook";

function CharacterCard({ character, bookId }) {
  const queryClient = useQueryClient();
  const [voicePrompt, setVoicePrompt] = useState(character.voice_design_prompt || "");
  const [saved, setSaved] = useState(false);

  const mutation = useMutation({
    mutationFn: (data) => updateCharacter(character.id, data),
    onSuccess: () => {
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      queryClient.invalidateQueries({ queryKey: ["audiobook-characters", bookId] });
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
        <p className="success">Saved — audio for this character will be regenerated.</p>
      )}
      <button onClick={handleSave} disabled={mutation.isPending}>
        {mutation.isPending ? "Saving…" : "Save Profile"}
      </button>
    </div>
  );
}

function CharacterRoster({ characters, bookId }) {
  if (!characters || characters.length === 0) {
    return (
      <p className="empty-state">
        No characters yet. Start the pipeline to generate the roster.
      </p>
    );
  }

  return (
    <div className="character-roster">
      {characters.map((char) => (
        <CharacterCard key={char.id} character={char} bookId={bookId} />
      ))}
    </div>
  );
}

export default CharacterRoster;
