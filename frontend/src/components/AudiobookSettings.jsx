import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getAudiobookSettings,
  testAudiobookLlm,
  testAudiobookTts,
  updateAudiobookSettings,
} from "../api/audiobook";

const DEFAULT_ROSTER_PROMPT_HINT =
  "Leave blank to use the built-in roster extraction prompt.";
const DEFAULT_DIARIZATION_PROMPT_HINT =
  "Leave blank to use the built-in diarization prompt.";

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
  const [ttsProvider, setTtsProvider] = useState("stub");
  const [ttsApiKey, setTtsApiKey] = useState("");
  const [ttsBaseUrl, setTtsBaseUrl] = useState("");
  const [ttsModel, setTtsModel] = useState("");
  const [ttsDefaultVoice, setTtsDefaultVoice] = useState("");
  const [rosterPrompt, setRosterPrompt] = useState("");
  const [diarizationPrompt, setDiarizationPrompt] = useState("");
  const [initialised, setInitialised] = useState(false);

  useEffect(() => {
    if (settings && !initialised) {
      setLlmProvider(settings.llm_provider || "stub");
      setLlmBaseUrl(settings.llm_base_url || "");
      setLlmModel(settings.llm_model || "");
      setTtsProvider(settings.tts_provider || "stub");
      setTtsBaseUrl(settings.tts_base_url || "");
      setTtsModel(settings.tts_model || "");
      setTtsDefaultVoice(settings.tts_default_voice || "");
      setRosterPrompt(settings.roster_prompt_template || "");
      setDiarizationPrompt(settings.diarization_prompt_template || "");
      setInitialised(true);
    }
  }, [initialised, settings]);

  const saveMutation = useMutation({
    mutationFn: (data) => updateAudiobookSettings(data),
    onSuccess: () => {
      setTtsApiKey("");
      queryClient.invalidateQueries({ queryKey: ["audiobook-settings"] });
    },
  });

  const buildPayload = () => {
    const payload = {
      llm_provider: llmProvider || null,
      llm_base_url: llmBaseUrl || null,
      llm_model: llmModel || null,
      tts_provider: ttsProvider || "stub",
      tts_base_url: ttsBaseUrl || null,
      tts_model: ttsModel || null,
      tts_default_voice: ttsDefaultVoice || null,
      roster_prompt_template: rosterPrompt || null,
      diarization_prompt_template: diarizationPrompt || null,
    };
    if (llmApiKey) {
      payload.llm_api_key = llmApiKey;
    }
    if (ttsApiKey) {
      payload.tts_api_key = ttsApiKey;
    }
    return payload;
  };

  const testMutation = useMutation({
    mutationFn: async () => {
      await updateAudiobookSettings(buildPayload());
      return testAudiobookLlm();
    },
    onSuccess: () => {
      setTtsApiKey("");
      queryClient.invalidateQueries({ queryKey: ["audiobook-settings"] });
    },
  });

  const testTtsMutation = useMutation({
    mutationFn: async () => {
      await updateAudiobookSettings(buildPayload());
      return testAudiobookTts();
    },
    onSuccess: () => {
      setTtsApiKey("");
      queryClient.invalidateQueries({ queryKey: ["audiobook-settings"] });
    },
  });

  const handleSave = (e) => {
    e.preventDefault();
    saveMutation.mutate(buildPayload());
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
            <select
              value={llmProvider}
              onChange={(e) => setLlmProvider(e.target.value)}
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="ollama">Ollama (local)</option>
              <option value="custom">Custom / Local</option>
              <option value="stub">Deterministic local harness</option>
            </select>
          </label>
          <label>
            API Key
            <input
              type="password"
              value={llmApiKey}
              onChange={(e) => setLlmApiKey(e.target.value)}
              placeholder={
                settings?.llm_api_key_set
                  ? "••••••••  (set — enter new key to change)"
                  : "Enter API key"
              }
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
          <div className="settings-actions-inline">
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                setLlmProvider("ollama");
                setLlmBaseUrl("http://127.0.0.1:11434");
                setLlmModel("qwen3.5:9b");
              }}
            >
              Use Recommended Local Ollama
            </button>
            <button
              type="button"
              onClick={() => testMutation.mutate()}
              disabled={testMutation.isPending}
            >
              {testMutation.isPending ? "Testing…" : "Save & Test LLM"}
            </button>
          </div>
          <p className="settings-hint">
            Recommended local default: <code>qwen3.5:9b</code> (6.6 GB). Run{" "}
            <code>ollama pull qwen3.5:9b</code> first. Story Manager uses
            Ollama&apos;s schema-constrained JSON output and disables thinking
            for predictable extraction latency.
          </p>
          {testMutation.isSuccess && (
            <p className="success">
              Connected to {testMutation.data.provider} /{" "}
              {testMutation.data.model || "local harness"}.
            </p>
          )}
          {testMutation.isError && (
            <p className="error">
              {testMutation.error?.message || "LLM test failed"}
            </p>
          )}
        </section>

        <section className="settings-section">
          <h3>Text-to-Speech Provider</h3>
          <label>
            Provider
            <select
              value={ttsProvider}
              onChange={(e) => {
                setTtsProvider(e.target.value);
                setTtsApiKey("");
              }}
            >
              <option value="omnivoice">OmniVoice</option>
              <option value="openai-compatible">
                OpenAI-compatible (Kokoro / local)
              </option>
              <option value="openai">OpenAI</option>
              <option value="elevenlabs">ElevenLabs</option>
              <option value="stub">Deterministic local harness</option>
            </select>
          </label>
          {ttsProvider !== "stub" && (
            <label>
              API Key
              <input
                type="password"
                value={ttsApiKey}
                onChange={(e) => setTtsApiKey(e.target.value)}
                placeholder={
                  settings?.tts_api_key_set
                    ? "••••••••  (set — enter new key to change)"
                    : ttsProvider === "omnivoice" ||
                        ttsProvider === "openai-compatible"
                      ? "Optional for local servers"
                      : "Enter API key"
                }
              />
            </label>
          )}
          {ttsProvider !== "stub" && (
            <label>
              Base URL
              <input
                type="url"
                value={ttsBaseUrl}
                onChange={(e) => setTtsBaseUrl(e.target.value)}
                placeholder={
                  ttsProvider === "omnivoice"
                    ? "http://your-omnivoice-server:8001"
                    : ttsProvider === "openai-compatible"
                      ? "http://your-tts-server:8880"
                      : "Leave blank for the provider default"
                }
              />
            </label>
          )}
          {["openai", "openai-compatible", "elevenlabs"].includes(
            ttsProvider,
          ) && (
            <label>
              Model
              <input
                type="text"
                value={ttsModel}
                onChange={(e) => setTtsModel(e.target.value)}
                placeholder={
                  ttsProvider === "openai-compatible"
                    ? "e.g. kokoro"
                    : ttsProvider === "openai"
                      ? "tts-1"
                      : "eleven_multilingual_v2"
                }
              />
            </label>
          )}
          {["openai", "openai-compatible", "elevenlabs"].includes(
            ttsProvider,
          ) && (
            <label>
              Default Voice ID
              <input
                type="text"
                value={ttsDefaultVoice}
                onChange={(e) => setTtsDefaultVoice(e.target.value)}
                placeholder={
                  ttsProvider === "openai-compatible"
                    ? "e.g. af_heart"
                    : ttsProvider === "openai"
                      ? "e.g. alloy"
                      : "ElevenLabs voice ID"
                }
              />
            </label>
          )}
          <div className="settings-actions-inline">
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                setTtsProvider("omnivoice");
                setTtsApiKey("");
                setTtsBaseUrl("http://127.0.0.1:8001");
                setTtsModel("");
                setTtsDefaultVoice("");
              }}
            >
              Use Local OmniVoice
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                setTtsProvider("openai-compatible");
                setTtsApiKey("");
                setTtsBaseUrl("http://127.0.0.1:8880");
                setTtsModel("kokoro");
                setTtsDefaultVoice("af_heart");
              }}
            >
              Use Local Kokoro
            </button>
            <button
              type="button"
              onClick={() => testTtsMutation.mutate()}
              disabled={testTtsMutation.isPending}
            >
              {testTtsMutation.isPending ? "Testing…" : "Save & Test TTS"}
            </button>
          </div>
          {testTtsMutation.isSuccess && (
            <p className="success">
              Connected to {testTtsMutation.data.provider}
              {testTtsMutation.data.model
                ? ` / ${testTtsMutation.data.model}`
                : ""}
              .
            </p>
          )}
          {testTtsMutation.isError && (
            <p className="error">
              {testTtsMutation.error?.message || "TTS test failed"}
            </p>
          )}
          <p className="settings-hint">
            OmniVoice uses descriptive voice profiles and expression tags.
            OpenAI-compatible and hosted APIs use voice IDs; set a default here
            and optionally override it on individual characters.
          </p>
          {ttsProvider === "omnivoice" && (
            <p className="settings-hint">
              Run <code>make run-omnivoice</code> for the bundled local adapter.
              It receives <code>POST /generate</code> and returns MP3 audio.
            </p>
          )}
          {ttsProvider === "openai-compatible" && (
            <p className="settings-hint">
              Compatible servers must implement{" "}
              <code>POST /v1/audio/speech</code>. Kokoro FastAPI is supported by
              the local preset.
            </p>
          )}
          {ttsProvider === "stub" && (
            <p className="settings-hint">
              The deterministic harness generates silent placeholder MP3s with
              realistic timing for offline validation.
            </p>
          )}
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
          <p className="error">
            {saveMutation.error?.message || "Save failed"}
          </p>
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
