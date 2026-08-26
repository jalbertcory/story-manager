import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  designCharacterVoice,
  getCharacterVoiceSampleUrl,
  rebuildCharacterRoster,
  setBookTtsProvider,
  shareCharacterRosterWithSeries,
  updateCharacter,
} from "../../api/audiobook";
import useLifecycleDefinitions from "../../hooks/useLifecycleDefinitions";

function CharacterCard({ character, bookId, pipelineActive, ttsProvider }) {
  const queryClient = useQueryClient();
  const [voicePrompt, setVoicePrompt] = useState(character.voice_prompt || "");
  const [voiceId, setVoiceId] = useState(character.tts_voice_id || "");
  const [voiceIdDirty, setVoiceIdDirty] = useState(false);
  const [voiceSeed, setVoiceSeed] = useState(character.tts_seed ?? "");
  const [saved, setSaved] = useState(false);
  const [sampleRevision, setSampleRevision] = useState(0);

  useEffect(() => {
    if (!voiceIdDirty) setVoiceId(character.tts_voice_id || "");
  }, [character.tts_voice_id, voiceIdDirty]);

  useEffect(() => {
    setVoiceSeed(character.tts_seed ?? "");
  }, [character.tts_seed]);

  const mutation = useMutation({
    mutationFn: (data) => updateCharacter(character.id, data),
    onSuccess: (updatedCharacter) => {
      setVoiceId(updatedCharacter.tts_voice_id || "");
      setVoiceSeed(updatedCharacter.tts_seed ?? "");
      setVoiceIdDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      queryClient.invalidateQueries({
        queryKey: ["audiobook-characters", bookId],
      });
      queryClient.invalidateQueries({ queryKey: ["audiobook-status", bookId] });
    },
  });

  const designMutation = useMutation({
    mutationFn: () =>
      designCharacterVoice(character.id, {
        voice_prompt: voicePrompt || null,
      }),
    onSuccess: (updatedCharacter) => {
      setVoiceId(updatedCharacter.tts_voice_id || "");
      setVoiceIdDirty(false);
      setSampleRevision(Date.now());
      queryClient.invalidateQueries({
        queryKey: ["audiobook-characters", bookId],
      });
      queryClient.invalidateQueries({ queryKey: ["audiobook-status", bookId] });
    },
  });

  const handleSave = () => {
    const payload = {
      voice_prompt: voicePrompt || null,
      tts_seed: voiceSeed === "" ? null : Number(voiceSeed),
    };
    if (voiceIdDirty) {
      payload.tts_voice_id = voiceId || null;
    }
    mutation.mutate(payload);
  };

  return (
    <div className="character-card">
      <div className="character-card-header">
        <strong>{character.name}</strong>
        {character.is_narrator && <span className="badge">Narrator</span>}
        {character.shared_series_name && (
          <span
            className="badge badge--success"
            title={`Shared across ${character.shared_series_name}`}
          >
            Series profile
          </span>
        )}
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
        Voice Profile
        <input
          type="text"
          value={voicePrompt}
          onChange={(e) => setVoicePrompt(e.target.value)}
          placeholder="e.g. [gender-male][pitch-low] Dry baritone, crisp diction, measured cadence"
        />
      </label>
      <p className="character-voice-hint">
        Tokens: <code>[gender-male|female|neutral]</code>{" "}
        <code>[pitch-low|medium|high]</code>{" "}
        <code>[speed-slow|normal|fast]</code>{" "}
        <code>[age-young|middle|old]</code>{" "}
        <code>[accent-british|american|…]</code>. Add a short acoustic
        description (timbre, resonance, diction, and cadence) so this character
        is distinguishable from the rest of the cast.
      </p>
      <label className="character-voice-label">
        Stable generation seed
        <input
          type="number"
          min="0"
          max="2147483647"
          value={voiceSeed}
          onChange={(event) => setVoiceSeed(event.target.value)}
          placeholder="Created automatically on first use"
        />
      </label>
      <label className="character-voice-label">
        Provider Voice ID
        <input
          type="text"
          value={voiceId}
          onChange={(e) => {
            setVoiceId(e.target.value);
            setVoiceIdDirty(true);
          }}
          placeholder="Optional; overrides the provider default voice"
        />
      </label>
      <p className="character-voice-hint">
        Used by fixed-voice providers such as OpenAI-compatible APIs and
        ElevenLabs. Local design-capable providers store a reusable reference
        voice here after it is designed.
        {character.tts_voice_provider
          ? ` Saved for ${character.tts_voice_provider}.`
          : ""}
      </p>
      {["omnivoice", "qwen3"].includes(ttsProvider) && (
        <div className="character-voice-design">
          <button
            onClick={() => designMutation.mutate()}
            disabled={designMutation.isPending || pipelineActive}
          >
            {designMutation.isPending
              ? "Designing sample…"
              : character.tts_voice_provider === ttsProvider
                ? "Replace Voice Design"
                : "Create Consistent Voice"}
          </button>
          {(character.tts_voice_provider === ttsProvider ||
            designMutation.isSuccess) && (
            <audio
              controls
              preload="none"
              src={getCharacterVoiceSampleUrl(character.id, sampleRevision)}
            >
              Your browser does not support audio playback.
            </audio>
          )}
          <p className="character-voice-hint">
            This creates one reference performance and reuses it for every
            generation block. Qwen3 also accepts preset IDs such as
            <code> preset:Ryan</code> and installed LoRA IDs such as
            <code> lora:narrator</code>. Replacing a reference updates the
            shared series roster and invalidates clips made with the previous
            voice.
          </p>
        </div>
      )}
      {designMutation.isError && (
        <p className="error">
          {designMutation.error?.message || "Voice design failed"}
        </p>
      )}
      {mutation.isError && (
        <p className="error">{mutation.error?.message || "Save failed"}</p>
      )}
      {saved && (
        <p className="success">
          Saved across the series. Existing clips were invalidated; use a
          chapter preview when you are ready to compare the voice.
        </p>
      )}
      <button onClick={handleSave} disabled={mutation.isPending}>
        {mutation.isPending ? "Saving…" : "Save Profile"}
      </button>
    </div>
  );
}

function CharacterRoster({
  characters,
  bookId,
  pipelineStatus,
  series,
  ttsProvider,
  ttsProviderLocked,
  availableTtsProviders = [],
}) {
  const queryClient = useQueryClient();
  const { data: lifecycleDefinitions } = useLifecycleDefinitions();
  const activeStatuses = new Set(
    lifecycleDefinitions?.audiobook_pipeline?.active_states ?? [],
  );
  const pipelineActive = activeStatuses.has(pipelineStatus);
  const providerOptions = availableTtsProviders.includes(ttsProvider)
    ? availableTtsProviders
    : [ttsProvider, ...availableTtsProviders].filter(Boolean);
  const [confirmRegenerate, setConfirmRegenerate] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState(ttsProvider || "");
  const [confirmProviderChange, setConfirmProviderChange] = useState(false);
  useEffect(() => {
    setSelectedProvider(ttsProvider || "");
    setConfirmProviderChange(false);
  }, [ttsProvider]);
  const providerMutation = useMutation({
    mutationFn: () => setBookTtsProvider(bookId, selectedProvider),
    onSuccess: () => {
      setConfirmProviderChange(false);
      queryClient.invalidateQueries({ queryKey: ["audiobook-status", bookId] });
      queryClient.invalidateQueries({
        queryKey: ["audiobook-characters", bookId],
      });
      queryClient.invalidateQueries({
        queryKey: ["audiobook-chapters", bookId],
      });
    },
  });
  const regenerateMutation = useMutation({
    mutationFn: () => rebuildCharacterRoster(bookId),
    onSuccess: () => {
      setConfirmRegenerate(false);
      queryClient.invalidateQueries({ queryKey: ["audiobook-status", bookId] });
      queryClient.invalidateQueries({
        queryKey: ["audiobook-characters", bookId],
      });
      queryClient.invalidateQueries({ queryKey: ["active-processing-jobs"] });
      queryClient.invalidateQueries({
        queryKey: ["audiobook-chapters", bookId],
      });
    },
  });
  const shareMutation = useMutation({
    mutationFn: () => shareCharacterRosterWithSeries(bookId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["audiobook-characters", bookId],
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
        <label>
          {series ? "Series TTS engine" : "Book TTS engine"}{" "}
          <select
            value={selectedProvider}
            onChange={(event) => {
              setSelectedProvider(event.target.value);
              setConfirmProviderChange(false);
            }}
            disabled={pipelineActive || providerMutation.isPending}
          >
            {providerOptions.map((provider) => (
              <option key={provider} value={provider}>
                {provider === "qwen3"
                  ? "Qwen3-TTS"
                  : provider === "omnivoice"
                    ? "OmniVoice"
                    : provider}
              </option>
            ))}
          </select>
        </label>
        <span>
          {ttsProviderLocked ? "Locked" : "Will lock on first generation"} to{" "}
          <strong>{ttsProvider}</strong>. Failover can use another endpoint for
          this engine, but never a different engine.
        </span>
        {selectedProvider &&
          selectedProvider !== ttsProvider &&
          (!confirmProviderChange ? (
            <button
              onClick={() => setConfirmProviderChange(true)}
              disabled={pipelineActive}
            >
              Change engine
            </button>
          ) : (
            <span className="confirm-inline">
              This clears incompatible voices and generated audio for the whole
              {series ? " series" : " book"}.{" "}
              <button
                className="btn-danger"
                onClick={() => providerMutation.mutate()}
                disabled={providerMutation.isPending}
              >
                {providerMutation.isPending
                  ? "Changing…"
                  : "Yes, change engine"}
              </button>{" "}
              <button
                className="btn-text"
                onClick={() => {
                  setSelectedProvider(ttsProvider || "");
                  setConfirmProviderChange(false);
                }}
              >
                Cancel
              </button>
            </span>
          ))}
        {providerMutation.isError && (
          <span className="error">{providerMutation.error?.message}</span>
        )}
      </div>
      <div className="roster-controls">
        <span>
          {characters.length} voice profiles. Regenerating preserves EPUB
          ingestion but clears speaker assignments and invalidates generated
          snippets. {series ? `Profiles can be shared across ${series}.` : ""}
        </span>
        {series && (
          <button
            onClick={() => shareMutation.mutate()}
            disabled={shareMutation.isPending || pipelineActive}
          >
            {shareMutation.isPending ? "Syncing series…" : "Sync Series Roster"}
          </button>
        )}
        {!confirmRegenerate ? (
          <button
            onClick={() => setConfirmRegenerate(true)}
            disabled={pipelineActive}
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
        {regenerateMutation.isSuccess && (
          <span className="success">
            Roster regeneration queued.{" "}
            <a href="/processing">View processing</a>
          </span>
        )}
        {shareMutation.isSuccess && (
          <span className="success">
            Shared profiles are now linked across {series}.
          </span>
        )}
        {shareMutation.isError && (
          <span className="error">{shareMutation.error?.message}</span>
        )}
      </div>
      <div className="character-roster">
        {characters.map((char) => (
          <CharacterCard
            key={char.id}
            character={char}
            bookId={bookId}
            pipelineActive={pipelineActive}
            ttsProvider={ttsProvider}
          />
        ))}
      </div>
    </>
  );
}

export default CharacterRoster;
