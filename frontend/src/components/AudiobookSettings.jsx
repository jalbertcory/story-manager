import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getAudiobookSettings, updateAudiobookSettings } from "../api/audiobook";

const DEFAULT_ROSTER_PROMPT_HINT = "Leave blank to use the built-in roster extraction prompt.";
const DEFAULT_DIARIZATION_PROMPT_HINT = "Leave blank to use the built-in diarization prompt.";

function AudiobookSettings() {
  const queryClient = useQueryClient();

  const { data: settings, isLoading } = useQuery({
    queryKey: ["audiobook-settings"],
    queryFn: getAudiobookSettings,
  });

  const [llmProvider, setLlmProvider] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [omnivoiceEndpoint, setOmnivoiceEndpoint] = useState("");
  const [rosterPrompt, setRosterPrompt] = useState("");
  const [diarizationPrompt, setDiarizationPrompt] = useState("");
  const [initialised, setInitialised] = useState(false);

  if (settings && !initialised) {
    setLlmProvider(settings.llm_provider || "openai");
    setLlmBaseUrl(settings.llm_base_url || "");
    setLlmModel(settings.llm_model || "");
    setOmnivoiceEndpoint(settings.omnivoice_endpoint || "");
    setRosterPrompt(settings.roster_prompt_template || "");
    setDiarizationPrompt(settings.diarization_prompt_template || "");
    setInitialised(true);
  }

  const saveMutation = useMutation({
    mutationFn: (data) => updateAudiobookSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["audiobook-settings"] });
    },
  });

  const handleSave = (e) => {
    e.preventDefault();
    const payload = {
      llm_provider: llmProvider || null,
      llm_base_url: llmBaseUrl || null,
      llm_model: llmModel || null,
      omnivoice_endpoint: omnivoiceEndpoint || null,
      roster_prompt_template: rosterPrompt || null,
      diarization_prompt_template: diarizationPrompt || null,
    };
    if (llmApiKey) {
      payload.llm_api_key = llmApiKey;
    }
    saveMutation.mutate(payload);
  };

  if (isLoading) return <p>Loading settings…</p>;

  return (
    <div className="settings-page">
      <h2>Audio &amp; AI Configuration</h2>
      <form onSubmit={handleSave}>
        <section className="settings-section">
          <h3>LLM Provider</h3>
          <label>
            Provider
            <select value={llmProvider} onChange={(e) => setLlmProvider(e.target.value)}>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="custom">Custom / Local</option>
            </select>
          </label>
          <label>
            API Key
            <input
              type="password"
              value={llmApiKey}
              onChange={(e) => setLlmApiKey(e.target.value)}
              placeholder={settings?.llm_api_key_set ? "••••••••  (set — enter new key to change)" : "Enter API key"}
            />
          </label>
          <label>
            Base URL
            <input
              type="url"
              value={llmBaseUrl}
              onChange={(e) => setLlmBaseUrl(e.target.value)}
              placeholder="https://api.openai.com  (leave blank for provider default)"
            />
          </label>
          <label>
            Model
            <input
              type="text"
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              placeholder="e.g. gpt-4o or claude-opus-4-7"
            />
          </label>
        </section>

        <section className="settings-section">
          <h3>OmniVoice TTS</h3>
          <label>
            Endpoint URL
            <input
              type="url"
              value={omnivoiceEndpoint}
              onChange={(e) => setOmnivoiceEndpoint(e.target.value)}
              placeholder="http://your-omnivoice-server:port"
            />
          </label>
          <p className="settings-hint">
            OmniVoice receives <code>POST /generate</code> with{" "}
            <code>{"{ \"voice\": \"[gender-male][pitch-low]\", \"text\": \"...\" }"}</code> and
            returns raw MP3 bytes.
          </p>
        </section>

        <section className="settings-section">
          <h3>Prompt Templates</h3>
          <label>
            Roster Extraction Prompt
            <textarea
              rows={6}
              value={rosterPrompt}
              onChange={(e) => setRosterPrompt(e.target.value)}
              placeholder={DEFAULT_ROSTER_PROMPT_HINT}
            />
          </label>
          <label>
            Diarization Prompt
            <textarea
              rows={6}
              value={diarizationPrompt}
              onChange={(e) => setDiarizationPrompt(e.target.value)}
              placeholder={DEFAULT_DIARIZATION_PROMPT_HINT}
            />
          </label>
        </section>

        {saveMutation.isError && (
          <p className="error">{saveMutation.error?.message || "Save failed"}</p>
        )}
        {saveMutation.isSuccess && <p className="success">Settings saved.</p>}

        <button type="submit" disabled={saveMutation.isPending}>
          {saveMutation.isPending ? "Saving…" : "Save Settings"}
        </button>
      </form>
    </div>
  );
}

export default AudiobookSettings;
