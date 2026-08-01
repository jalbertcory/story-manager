import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getAudiobookSettings,
  testAudiobookLlm,
  testAudiobookTranscription,
  testAudiobookTts,
  updateAudiobookSettings,
} from "../api/audiobook";

const DEFAULT_ROSTER_PROMPT_HINT =
  "Leave blank to use the built-in roster extraction prompt.";
const DEFAULT_DIARIZATION_PROMPT_HINT =
  "Leave blank to use the built-in diarization prompt.";

let endpointSequence = 0;

function endpointId(capability) {
  endpointSequence += 1;
  return `${capability}-${Date.now()}-${endpointSequence}`;
}

const CAPABILITIES = {
  llm: {
    title: "LLM Endpoints",
    description:
      "Used for character extraction and speaker assignment. Endpoints are tried from top to bottom.",
    providers: [
      ["openai", "OpenAI"],
      ["anthropic", "Anthropic"],
      ["ollama", "Ollama (local)"],
      ["custom", "Custom / Local"],
      ["stub", "Deterministic local harness"],
    ],
    defaultProvider: "ollama",
    modelPlaceholder: "e.g. qwen3.5:9b or gpt-4o",
    baseUrlPlaceholder: "http://model-host:11434",
  },
  tts: {
    title: "Text-to-Speech Endpoints",
    description:
      "Used to render narration. Put a fast, sometimes-available host above an always-on fallback.",
    providers: [
      ["omnivoice", "OmniVoice"],
      ["openai-compatible", "OpenAI-compatible (Kokoro / local)"],
      ["openai", "OpenAI"],
      ["elevenlabs", "ElevenLabs"],
      ["stub", "Deterministic local harness"],
    ],
    defaultProvider: "omnivoice",
    modelPlaceholder: "e.g. kokoro or tts-1",
    baseUrlPlaceholder: "http://speech-host:8001",
  },
  transcription: {
    title: "Speech-to-Text Endpoints",
    description:
      "Used to align imported human narration with EPUB text and word timestamps.",
    providers: [
      ["whisperx", "WhisperX service"],
      ["none", "Not configured"],
    ],
    defaultProvider: "whisperx",
    modelPlaceholder: "e.g. large-v3",
    baseUrlPlaceholder: "http://whisper-host:8002",
  },
};

function legacyEndpoint(settings, capability) {
  const prefix = capability === "transcription" ? "transcription" : capability;
  const defaults = { llm: "stub", tts: "stub", transcription: "none" };
  return {
    id: `legacy-${capability}`,
    name: "Primary",
    provider: settings?.[`${prefix}_provider`] || defaults[capability],
    api_key_set: Boolean(settings?.[`${prefix}_api_key_set`]),
    base_url: settings?.[`${prefix}_base_url`] || "",
    model: settings?.[`${prefix}_model`] || "",
    default_voice: settings?.tts_default_voice || "",
    language: settings?.transcription_language || "auto",
  };
}

function initialiseEndpoints(settings, capability) {
  const stored = settings?.[`${capability}_endpoints`];
  const endpoints = stored?.length ? stored : [legacyEndpoint(settings, capability)];
  return endpoints.map((endpoint) => ({
    ...endpoint,
    base_url: endpoint.base_url || "",
    model: endpoint.model || "",
    default_voice: endpoint.default_voice || "",
    language: endpoint.language || "auto",
    api_key: "",
    api_key_dirty: false,
  }));
}

function newEndpoint(capability, values = {}) {
  return {
    id: endpointId(capability),
    name: values.name || `New ${capability.toUpperCase()} host`,
    provider: values.provider || CAPABILITIES[capability].defaultProvider,
    api_key: "",
    api_key_set: false,
    api_key_dirty: false,
    base_url: values.base_url || "",
    model: values.model || "",
    default_voice: values.default_voice || "",
    language: values.language || "auto",
  };
}

function EndpointPoolEditor({ capability, endpoints, setEndpoints }) {
  const config = CAPABILITIES[capability];

  const update = (index, field, value) => {
    setEndpoints((current) =>
      current.map((endpoint, endpointIndex) => {
        if (endpointIndex !== index) return endpoint;
        if (field === "provider") {
          return {
            ...endpoint,
            provider: value,
            api_key: "",
            api_key_set: false,
            api_key_dirty: true,
          };
        }
        if (field === "api_key") {
          return { ...endpoint, api_key: value, api_key_dirty: true };
        }
        return { ...endpoint, [field]: value };
      }),
    );
  };

  const move = (index, direction) => {
    setEndpoints((current) => {
      const target = index + direction;
      if (target < 0 || target >= current.length) return current;
      const reordered = [...current];
      [reordered[index], reordered[target]] = [
        reordered[target],
        reordered[index],
      ];
      return reordered;
    });
  };

  const addPreset = () => {
    const presets = {
      llm: {
        name: "Local Ollama",
        provider: "ollama",
        base_url: "http://127.0.0.1:11434",
        model: "qwen3.5:9b",
      },
      tts: {
        name: "Local OmniVoice",
        provider: "omnivoice",
        base_url: "http://127.0.0.1:8001",
      },
      transcription: {
        name: "Local WhisperX",
        provider: "whisperx",
        base_url: "http://127.0.0.1:8002",
        model: "large-v3",
        language: "en",
      },
    };
    setEndpoints((current) => [...current, newEndpoint(capability, presets[capability])]);
  };

  return (
    <>
      <div className="endpoint-pool-heading">
        <div>
          <h3>{config.title}</h3>
          <p className="settings-hint">{config.description}</p>
        </div>
        <button type="button" className="btn-secondary" onClick={addPreset}>
          + Add endpoint
        </button>
      </div>
      <div className="endpoint-pool">
        {endpoints.map((endpoint, index) => {
          const disabled = ["stub", "none"].includes(endpoint.provider);
          return (
            <article className="endpoint-card" key={endpoint.id}>
              <header className="endpoint-card-header">
                <span className="endpoint-priority">Priority {index + 1}</span>
                <div className="endpoint-order-actions">
                  <button
                    type="button"
                    className="btn-secondary endpoint-order-button"
                    aria-label={`Move ${endpoint.name} up`}
                    disabled={index === 0}
                    onClick={() => move(index, -1)}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    className="btn-secondary endpoint-order-button"
                    aria-label={`Move ${endpoint.name} down`}
                    disabled={index === endpoints.length - 1}
                    onClick={() => move(index, 1)}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    className="btn-secondary endpoint-remove-button"
                    disabled={endpoints.length === 1}
                    onClick={() =>
                      setEndpoints((current) =>
                        current.filter((_, endpointIndex) => endpointIndex !== index),
                      )
                    }
                  >
                    Remove
                  </button>
                </div>
              </header>
              <div className="endpoint-fields">
                <label>
                  Name
                  <input
                    value={endpoint.name}
                    onChange={(event) => update(index, "name", event.target.value)}
                    placeholder="Gaming PC"
                  />
                </label>
                <label>
                  Provider
                  <select
                    value={endpoint.provider}
                    onChange={(event) => update(index, "provider", event.target.value)}
                  >
                    {config.providers.map(([value, label]) => (
                      <option value={value} key={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                {!disabled && (
                  <label>
                    API Key
                    <input
                      type="password"
                      value={endpoint.api_key}
                      onChange={(event) => update(index, "api_key", event.target.value)}
                      placeholder={
                        endpoint.api_key_set
                          ? "••••••••  (set — enter a new key to change)"
                          : "Optional for trusted local hosts"
                      }
                    />
                  </label>
                )}
                {!disabled && (
                  <label>
                    Base URL
                    <input
                      type="url"
                      value={endpoint.base_url}
                      onChange={(event) => update(index, "base_url", event.target.value)}
                      placeholder={config.baseUrlPlaceholder}
                    />
                  </label>
                )}
                {!disabled && (
                  <label>
                    Model
                    <input
                      value={endpoint.model}
                      onChange={(event) => update(index, "model", event.target.value)}
                      placeholder={config.modelPlaceholder}
                    />
                  </label>
                )}
                {capability === "tts" &&
                  !disabled &&
                  endpoint.provider !== "omnivoice" && (
                    <label>
                      Default Voice ID
                      <input
                        value={endpoint.default_voice}
                        onChange={(event) =>
                          update(index, "default_voice", event.target.value)
                        }
                        placeholder="e.g. af_heart or alloy"
                      />
                    </label>
                  )}
                {capability === "transcription" && !disabled && (
                  <label>
                    Language
                    <input
                      value={endpoint.language}
                      onChange={(event) => update(index, "language", event.target.value)}
                      placeholder="auto or en"
                    />
                  </label>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </>
  );
}

function serialiseEndpoints(endpoints) {
  return endpoints.map((endpoint) => {
    const payload = {
      id: endpoint.id,
      name: endpoint.name,
      provider: endpoint.provider,
      base_url: endpoint.base_url || null,
      model: endpoint.model || null,
      default_voice: endpoint.default_voice || null,
      language: endpoint.language || null,
    };
    if (endpoint.api_key_dirty) payload.api_key = endpoint.api_key || null;
    return payload;
  });
}

function useEndpointTestMutation(testFunction, buildPayload, refreshSettings) {
  return useMutation({
    mutationFn: async () => {
      await updateAudiobookSettings(buildPayload());
      return testFunction();
    },
    onSuccess: refreshSettings,
  });
}

function AudiobookSettings() {
  const queryClient = useQueryClient();
  const { data: settings, isLoading } = useQuery({
    queryKey: ["audiobook-settings"],
    queryFn: getAudiobookSettings,
  });

  const [llmEndpoints, setLlmEndpoints] = useState([]);
  const [ttsEndpoints, setTtsEndpoints] = useState([]);
  const [transcriptionEndpoints, setTranscriptionEndpoints] = useState([]);
  const [rosterPrompt, setRosterPrompt] = useState("");
  const [diarizationPrompt, setDiarizationPrompt] = useState("");
  const [initialised, setInitialised] = useState(false);

  useEffect(() => {
    if (settings && !initialised) {
      setLlmEndpoints(initialiseEndpoints(settings, "llm"));
      setTtsEndpoints(initialiseEndpoints(settings, "tts"));
      setTranscriptionEndpoints(initialiseEndpoints(settings, "transcription"));
      setRosterPrompt(settings.roster_prompt_template || "");
      setDiarizationPrompt(settings.diarization_prompt_template || "");
      setInitialised(true);
    }
  }, [initialised, settings]);

  const buildPayload = () => ({
    llm_endpoints: serialiseEndpoints(llmEndpoints),
    tts_endpoints: serialiseEndpoints(ttsEndpoints),
    transcription_endpoints: serialiseEndpoints(transcriptionEndpoints),
    roster_prompt_template: rosterPrompt || null,
    diarization_prompt_template: diarizationPrompt || null,
  });

  const refreshSettings = () => {
    const clearTypedSecrets = (current) =>
      current.map((endpoint) => ({
        ...endpoint,
        api_key_set: endpoint.api_key_dirty
          ? Boolean(endpoint.api_key)
          : endpoint.api_key_set,
        api_key: "",
        api_key_dirty: false,
      }));
    setLlmEndpoints(clearTypedSecrets);
    setTtsEndpoints(clearTypedSecrets);
    setTranscriptionEndpoints(clearTypedSecrets);
    queryClient.invalidateQueries({ queryKey: ["audiobook-settings"] });
  };

  const saveMutation = useMutation({
    mutationFn: () => updateAudiobookSettings(buildPayload()),
    onSuccess: refreshSettings,
  });

  const llmTest = useEndpointTestMutation(
    testAudiobookLlm,
    buildPayload,
    refreshSettings,
  );
  const ttsTest = useEndpointTestMutation(
    testAudiobookTts,
    buildPayload,
    refreshSettings,
  );
  const transcriptionTest = useEndpointTestMutation(
    testAudiobookTranscription,
    buildPayload,
    refreshSettings,
  );

  const handleSave = (event) => {
    event.preventDefault();
    saveMutation.mutate();
  };

  if (isLoading || !initialised) return <p>Loading settings…</p>;

  const testStatus = (mutation, label) => (
    <div className="endpoint-test-status">
      <button
        type="button"
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
      >
        {mutation.isPending ? "Testing pool…" : `Save & Test ${label}`}
      </button>
      {mutation.isSuccess && (
        <p className="success">
          Connected{mutation.data.endpoint ? ` via ${mutation.data.endpoint}` : ""} to{" "}
          {mutation.data.provider}
          {mutation.data.model ? ` / ${mutation.data.model}` : ""}.
        </p>
      )}
      {mutation.isError && (
        <p className="error">{mutation.error?.message || `${label} test failed`}</p>
      )}
    </div>
  );

  return (
    <div className="settings-page">
      <h2>Audio &amp; AI Configuration</h2>
      <p className="settings-hint endpoint-routing-hint">
        Requests use the highest-priority available endpoint. Connection or model
        failures put that endpoint on a 60-second cooldown, then the next request
        tries it again. No background polling runs when there is no work.
      </p>
      <form onSubmit={handleSave}>
        <section className="settings-section">
          <EndpointPoolEditor
            capability="llm"
            endpoints={llmEndpoints}
            setEndpoints={setLlmEndpoints}
          />
          {testStatus(llmTest, "LLM")}
        </section>

        <section className="settings-section">
          <EndpointPoolEditor
            capability="tts"
            endpoints={ttsEndpoints}
            setEndpoints={setTtsEndpoints}
          />
          {testStatus(ttsTest, "TTS")}
        </section>

        <section className="settings-section">
          <EndpointPoolEditor
            capability="transcription"
            endpoints={transcriptionEndpoints}
            setEndpoints={setTranscriptionEndpoints}
          />
          {testStatus(transcriptionTest, "Transcription")}
        </section>

        <section className="settings-section">
          <h3>Prompt Templates</h3>
          <label>
            Roster Extraction Prompt
            <textarea
              rows={6}
              value={rosterPrompt}
              onChange={(event) => setRosterPrompt(event.target.value)}
              placeholder={DEFAULT_ROSTER_PROMPT_HINT}
            />
          </label>
          <label>
            Diarization Prompt
            <textarea
              rows={6}
              value={diarizationPrompt}
              onChange={(event) => setDiarizationPrompt(event.target.value)}
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
