import type { Dispatch, SetStateAction, FormEvent } from "react";
import type { components } from "../api/schema";
type Capability = "llm" | "tts" | "transcription";
type Settings = components["schemas"]["SettingsResponse"];
type EndpointForm = {
  id: string;
  name: string;
  provider: string;
  api_key: string;
  api_key_set: boolean;
  api_key_dirty: boolean;
  base_url: string;
  model: string;
  default_voice: string;
  language: string;
};

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getAudiobookEndpointStats,
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

function endpointId(capability: Capability) {
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
      ["qwen3", "Qwen3-TTS (local)"],
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

function legacyEndpoint(
  settings: Settings | undefined,
  capability: Capability,
) {
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

function initialiseEndpoints(
  settings: Settings | undefined,
  capability: Capability,
): EndpointForm[] {
  const stored = settings?.[`${capability}_endpoints`];
  const endpoints = stored?.length
    ? stored
    : [legacyEndpoint(settings, capability)];
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

function newEndpoint(
  capability: Capability,
  values: Partial<EndpointForm> = {},
): EndpointForm {
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

function EndpointPoolEditor({
  capability,
  endpoints,
  setEndpoints,
}: {
  capability: Capability;
  endpoints: EndpointForm[];
  setEndpoints: Dispatch<SetStateAction<EndpointForm[]>>;
}) {
  const config = CAPABILITIES[capability];

  const update = (
    index: number,
    field:
      | "name"
      | "provider"
      | "api_key"
      | "base_url"
      | "model"
      | "default_voice"
      | "language",
    value: string,
  ) => {
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

  const move = (index: number, direction: number) => {
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
    setEndpoints((current) => [
      ...current,
      newEndpoint(capability, presets[capability]),
    ]);
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
                        current.filter(
                          (_, endpointIndex) => endpointIndex !== index,
                        ),
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
                    onChange={(event) =>
                      update(index, "name", event.target.value)
                    }
                    placeholder="Gaming PC"
                  />
                </label>
                <label>
                  Provider
                  <select
                    value={endpoint.provider}
                    onChange={(event) =>
                      update(index, "provider", event.target.value)
                    }
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
                      onChange={(event) =>
                        update(index, "api_key", event.target.value)
                      }
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
                      onChange={(event) =>
                        update(index, "base_url", event.target.value)
                      }
                      placeholder={config.baseUrlPlaceholder}
                    />
                  </label>
                )}
                {!disabled && (
                  <label>
                    Model
                    <input
                      value={endpoint.model}
                      onChange={(event) =>
                        update(index, "model", event.target.value)
                      }
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
                      onChange={(event) =>
                        update(index, "language", event.target.value)
                      }
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

function serialiseEndpoints(endpoints: EndpointForm[]) {
  return endpoints.map((endpoint) => {
    const payload: components["schemas"]["EndpointUpdate"] = {
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

function useEndpointTestMutation<T>(
  testFunction: () => Promise<T>,
  buildPayload: () => components["schemas"]["SettingsUpdate"],
  refreshSettings: () => void,
) {
  return useMutation({
    mutationFn: async () => {
      await updateAudiobookSettings(buildPayload());
      return testFunction();
    },
    onSuccess: refreshSettings,
  });
}

function formatDuration(milliseconds: number | null | undefined) {
  if (milliseconds === null || milliseconds === undefined) return "—";
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  if (milliseconds < 60_000) return `${(milliseconds / 1000).toFixed(1)} s`;
  return `${(milliseconds / 60_000).toFixed(1)} min`;
}

function EndpointMetrics({
  stats,
  capability,
  isLoading,
  error,
  onRefresh,
  isRefreshing,
}: {
  stats: components["schemas"]["EndpointStats"][];
  capability: string;
  isLoading: boolean;
  error: Error | null;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  return (
    <div className="llm-metrics">
      <div className="llm-metrics-heading">
        <div>
          <h4>Connection performance</h4>
          <p className="settings-hint">
            Successful {capability} requests and endpoint failures are recorded
            from this upgrade onward. Latency is measured end-to-end for each
            endpoint attempt.
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary"
          onClick={onRefresh}
          disabled={isRefreshing}
        >
          {isRefreshing ? "Refreshing…" : "Refresh metrics"}
        </button>
      </div>
      {isLoading && (
        <p className="settings-hint">Loading connection metrics…</p>
      )}
      {error && (
        <p className="error">
          {error.message || "Failed to load connection metrics"}
        </p>
      )}
      {!isLoading && !error && stats.length === 0 && (
        <p className="settings-hint">
          Save an LLM endpoint to begin collecting metrics.
        </p>
      )}
      {stats.length > 0 && (
        <div className="llm-metric-grid">
          {stats.map((endpoint) => (
            <article className="llm-metric-card" key={endpoint.endpoint_id}>
              <header>
                <div>
                  <strong>{endpoint.name}</strong>
                  <span>
                    {endpoint.provider}
                    {endpoint.model ? ` · ${endpoint.model}` : ""}
                  </span>
                </div>
                <span className="llm-success-rate">
                  {endpoint.success_rate === null
                    ? "No data"
                    : `${endpoint.success_rate}% answered`}
                </span>
              </header>
              <dl className="llm-metric-summary">
                <div>
                  <dt>Answered</dt>
                  <dd>{endpoint.answered}</dd>
                </div>
                <div>
                  <dt>Failed attempts</dt>
                  <dd>{endpoint.failed}</dd>
                </div>
                <div>
                  <dt>Average</dt>
                  <dd>{formatDuration(endpoint.average_ms)}</dd>
                </div>
                <div>
                  <dt>P50</dt>
                  <dd>{formatDuration(endpoint.p50_ms)}</dd>
                </div>
                <div>
                  <dt>P95</dt>
                  <dd>{formatDuration(endpoint.p95_ms)}</dd>
                </div>
                <div>
                  <dt>Last 24h</dt>
                  <dd>{endpoint.answered_24h}</dd>
                </div>
              </dl>
              <div
                className="llm-speed-breakdown"
                aria-label={`${endpoint.name} speed breakdown`}
              >
                <span>
                  &lt;5s <strong>{endpoint.speed_buckets.under_5s}</strong>
                </span>
                <span>
                  5–15s <strong>{endpoint.speed_buckets.from_5s_to_15s}</strong>
                </span>
                <span>
                  15–60s{" "}
                  <strong>{endpoint.speed_buckets.from_15s_to_60s}</strong>
                </span>
                <span>
                  60s+ <strong>{endpoint.speed_buckets.over_60s}</strong>
                </span>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function AudiobookSettings() {
  const queryClient = useQueryClient();
  const { data: settings, isLoading } = useQuery({
    queryKey: ["audiobook-settings"],
    queryFn: getAudiobookSettings,
  });
  const endpointStatsQuery = useQuery({
    queryKey: ["audiobook-endpoint-stats"],
    queryFn: getAudiobookEndpointStats,
    refetchInterval: 30_000,
  });

  const [llmEndpoints, setLlmEndpoints] = useState<EndpointForm[]>([]);
  const [ttsEndpoints, setTtsEndpoints] = useState<EndpointForm[]>([]);
  const [transcriptionEndpoints, setTranscriptionEndpoints] = useState<
    EndpointForm[]
  >([]);
  const [rosterPrompt, setRosterPrompt] = useState("");
  const [diarizationPrompt, setDiarizationPrompt] = useState("");
  const [maxBlockChars, setMaxBlockChars] = useState<number | string>(500);
  const [voiceSimilarityThreshold, setVoiceSimilarityThreshold] = useState<
    number | string
  >(0.45);
  const [qualityAttempts, setQualityAttempts] = useState<number | string>(3);
  const [initialised, setInitialised] = useState(false);

  useEffect(() => {
    if (settings && !initialised) {
      setLlmEndpoints(initialiseEndpoints(settings, "llm"));
      setTtsEndpoints(initialiseEndpoints(settings, "tts"));
      setTranscriptionEndpoints(initialiseEndpoints(settings, "transcription"));
      setRosterPrompt(settings.roster_prompt_template || "");
      setDiarizationPrompt(settings.diarization_prompt_template || "");
      setMaxBlockChars(settings.tts_max_block_chars ?? 500);
      setVoiceSimilarityThreshold(
        settings.tts_voice_similarity_threshold ?? 0.45,
      );
      setQualityAttempts(settings.tts_quality_attempts ?? 3);
      setInitialised(true);
    }
  }, [initialised, settings]);

  const buildPayload = () => ({
    llm_endpoints: serialiseEndpoints(llmEndpoints),
    tts_endpoints: serialiseEndpoints(ttsEndpoints),
    transcription_endpoints: serialiseEndpoints(transcriptionEndpoints),
    roster_prompt_template: rosterPrompt || null,
    diarization_prompt_template: diarizationPrompt || null,
    tts_max_block_chars: Number(maxBlockChars),
    tts_voice_similarity_threshold: Number(voiceSimilarityThreshold),
    tts_quality_attempts: Number(qualityAttempts),
  });

  const refreshSettings = () => {
    const clearTypedSecrets = (current: EndpointForm[]) =>
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
    queryClient.invalidateQueries({ queryKey: ["audiobook-endpoint-stats"] });
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

  const handleSave = (event: FormEvent) => {
    event.preventDefault();
    saveMutation.mutate();
  };

  if (isLoading || !initialised) return <p>Loading settings…</p>;

  const testStatus = (
    mutation:
      | ReturnType<
          typeof useEndpointTestMutation<
            Awaited<ReturnType<typeof testAudiobookLlm>>
          >
        >
      | ReturnType<
          typeof useEndpointTestMutation<
            Awaited<ReturnType<typeof testAudiobookTts>>
          >
        >
      | ReturnType<
          typeof useEndpointTestMutation<
            Awaited<ReturnType<typeof testAudiobookTranscription>>
          >
        >,
    label: string,
  ) => {
    const results = mutation.data?.results;
    const readyCount =
      results?.filter((result) => result.status === "ready").length ?? 0;
    return (
      <div className="endpoint-test-status">
        <button
          type="button"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
        >
          {mutation.isPending ? "Testing pool…" : `Save & Test ${label}`}
        </button>
        {mutation.isSuccess && !results && (
          <p className="success">
            Connected
            {mutation.data.endpoint
              ? ` via ${mutation.data.endpoint}`
              : ""} to {mutation.data.provider}
            {mutation.data.model ? ` / ${mutation.data.model}` : ""}.
          </p>
        )}
        {mutation.isSuccess && results && (
          <div
            className="endpoint-test-results"
            aria-label={`${label} endpoint test results`}
          >
            <p
              className={
                readyCount === results.length && results.length > 0
                  ? "success"
                  : readyCount > 0
                    ? "endpoint-test-partial"
                    : "error"
              }
            >
              {readyCount} of {results.length} endpoints connected.
            </p>
            <div className="endpoint-test-result-list">
              {results.map((result) => (
                <article
                  className={`endpoint-test-result endpoint-test-result-${result.status}`}
                  key={result.endpoint_id || result.priority}
                >
                  <div className="endpoint-test-result-heading">
                    <div>
                      <span>Priority {result.priority}</span>
                      <strong>{result.endpoint || "Unnamed endpoint"}</strong>
                      <small>
                        {result.provider}
                        {result.model ? ` · ${result.model}` : ""}
                      </small>
                    </div>
                    <span
                      className={
                        result.status === "ready" ? "success" : "error"
                      }
                    >
                      {result.status === "ready" ? "Connected" : "Failed"}
                      {result.duration_ms !== null &&
                      result.duration_ms !== undefined
                        ? ` · ${formatDuration(result.duration_ms)}`
                        : ""}
                    </span>
                  </div>
                  {result.error && <p className="error">{result.error}</p>}
                </article>
              ))}
            </div>
          </div>
        )}
        {mutation.isError && (
          <p className="error">
            {mutation.error?.message || `${label} test failed`}
          </p>
        )}
      </div>
    );
  };

  return (
    <div className="settings-page">
      <h2>Audio &amp; AI Configuration</h2>
      <p className="settings-hint endpoint-routing-hint">
        Services are tried in priority order. If one fails, it is skipped for 60
        seconds before being tried again.
      </p>
      <form onSubmit={handleSave}>
        <section className="settings-section">
          <EndpointPoolEditor
            capability="llm"
            endpoints={llmEndpoints}
            setEndpoints={setLlmEndpoints}
          />
          {testStatus(llmTest, "LLM")}
          <EndpointMetrics
            stats={endpointStatsQuery.data?.llm || []}
            capability="LLM"
            isLoading={endpointStatsQuery.isLoading}
            error={endpointStatsQuery.error}
            onRefresh={() => endpointStatsQuery.refetch()}
            isRefreshing={endpointStatsQuery.isFetching}
          />
        </section>

        <section className="settings-section">
          <EndpointPoolEditor
            capability="tts"
            endpoints={ttsEndpoints}
            setEndpoints={setTtsEndpoints}
          />
          {testStatus(ttsTest, "TTS")}
          <EndpointMetrics
            stats={endpointStatsQuery.data?.tts || []}
            capability="TTS"
            isLoading={endpointStatsQuery.isLoading}
            error={endpointStatsQuery.error}
            onRefresh={() => endpointStatsQuery.refetch()}
            isRefreshing={endpointStatsQuery.isFetching}
          />
          <div className="endpoint-fields">
            <label>
              Same-speaker block size
              <input
                type="number"
                min="100"
                max="2000"
                value={maxBlockChars}
                onChange={(event) => setMaxBlockChars(event.target.value)}
              />
              <span className="settings-hint">
                Adjacent sentences use one longer performance up to this many
                characters, then are sliced back into reader cues.
              </span>
            </label>
            <label>
              Minimum voice similarity
              <input
                type="number"
                min="-1"
                max="1"
                step="0.01"
                value={voiceSimilarityThreshold}
                onChange={(event) =>
                  setVoiceSimilarityThreshold(event.target.value)
                }
              />
              <span className="settings-hint">
                Local cloned voices below this WavLM score are regenerated.
              </span>
            </label>
            <label>
              Voice quality attempts
              <input
                type="number"
                min="1"
                max="10"
                value={qualityAttempts}
                onChange={(event) => setQualityAttempts(event.target.value)}
              />
            </label>
          </div>
        </section>

        <section className="settings-section">
          <EndpointPoolEditor
            capability="transcription"
            endpoints={transcriptionEndpoints}
            setEndpoints={setTranscriptionEndpoints}
          />
          {testStatus(transcriptionTest, "Transcription")}
          <EndpointMetrics
            stats={endpointStatsQuery.data?.transcription || []}
            capability="speech-to-text"
            isLoading={endpointStatsQuery.isLoading}
            error={endpointStatsQuery.error}
            onRefresh={() => endpointStatsQuery.refetch()}
            isRefreshing={endpointStatsQuery.isFetching}
          />
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
