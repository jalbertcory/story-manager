import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AudiobookSettings from "./AudiobookSettings";
import { renderWithClient } from "../test-utils";

describe("AudiobookSettings", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("does not carry a typed API key to a newly selected TTS provider", async () => {
    const updates = [];
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/audiobook/settings" && !options) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              llm_provider: "stub",
              llm_api_key_set: false,
              tts_provider: "openai",
              tts_api_key_set: false,
              tts_model: "tts-1",
              tts_default_voice: "alloy",
            }),
        });
      }
      if (
        url === "/api/audiobook/settings" &&
        options?.method === "PUT"
      ) {
        const body = JSON.parse(options.body);
        updates.push(body);
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              ...body,
              llm_api_key_set: false,
              tts_api_key_set: Boolean(body.tts_api_key),
            }),
        });
      }
      if (
        url === "/api/audiobook/settings/test-tts" &&
        options?.method === "POST"
      ) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              status: "ready",
              provider: "openai-compatible",
              model: "kokoro",
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(<AudiobookSettings />);

    const providerSelect = (await screen.findAllByRole("combobox"))[1];
    const ttsApiKeyInput = screen.getByLabelText("API Key");
    fireEvent.change(ttsApiKeyInput, { target: { value: "openai-secret" } });
    fireEvent.change(providerSelect, {
      target: { value: "openai-compatible" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save & Test TTS" }));

    await waitFor(() => expect(updates).toHaveLength(1));
    expect(updates[0].tts_endpoints[0].provider).toBe("openai-compatible");
    expect(updates[0].tts_endpoints[0].api_key).toBeNull();
  });

  it("reorders endpoint priority before saving", async () => {
    const updates = [];
    globalThis.fetch = vi.fn((url, options) => {
      if (url === "/api/audiobook/settings" && !options) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              llm_endpoints: [
                {
                  id: "always-on",
                  name: "Always-on mini PC",
                  provider: "ollama",
                  base_url: "http://mini:11434",
                  model: "qwen3.5:9b",
                },
                {
                  id: "gaming-pc",
                  name: "Gaming PC",
                  provider: "ollama",
                  base_url: "http://gaming:11434",
                  model: "qwen3.5:27b",
                },
              ],
              tts_provider: "stub",
              transcription_provider: "none",
            }),
        });
      }
      if (url === "/api/audiobook/settings" && options?.method === "PUT") {
        updates.push(JSON.parse(options.body));
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    renderWithClient(<AudiobookSettings />);

    await screen.findByDisplayValue("Gaming PC");
    fireEvent.click(
      screen.getByRole("button", { name: "Move Gaming PC up" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save Settings" }));

    await waitFor(() => expect(updates).toHaveLength(1));
    expect(updates[0].llm_endpoints.map((endpoint) => endpoint.id)).toEqual([
      "gaming-pc",
      "always-on",
    ]);
  });

  it("compares request counts and speed metrics for LLM endpoints", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/audiobook/settings") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              llm_endpoints: [
                {
                  id: "gaming-pc",
                  name: "Gaming PC",
                  provider: "ollama",
                  model: "qwen3.5:27b",
                },
              ],
              tts_provider: "stub",
              transcription_provider: "none",
            }),
        });
      }
      if (url === "/api/audiobook/settings/endpoint-stats") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              llm: [
                {
                  endpoint_id: "gaming-pc",
                  name: "Gaming PC",
                  provider: "ollama",
                  model: "qwen3.5:27b",
                  requests: 10,
                  answered: 9,
                  failed: 1,
                  success_rate: 90,
                  average_ms: 2400,
                  p50_ms: 1900,
                  p95_ms: 5200,
                  answered_24h: 3,
                  speed_buckets: {
                    under_5s: 8,
                    from_5s_to_15s: 1,
                    from_15s_to_60s: 0,
                    over_60s: 0,
                  },
                },
              ],
              tts: [
                {
                  endpoint_id: "tts-host",
                  name: "TTS Host",
                  provider: "omnivoice",
                  requests: 5,
                  answered: 5,
                  failed: 0,
                  success_rate: 100,
                  average_ms: 800,
                  p50_ms: 750,
                  p95_ms: 1100,
                  answered_24h: 2,
                  speed_buckets: {
                    under_5s: 5,
                    from_5s_to_15s: 0,
                    from_15s_to_60s: 0,
                    over_60s: 0,
                  },
                },
              ],
              transcription: [
                {
                  endpoint_id: "stt-host",
                  name: "Speech Host",
                  provider: "whisperx",
                  requests: 2,
                  answered: 1,
                  failed: 1,
                  success_rate: 50,
                  average_ms: 65_000,
                  p50_ms: 65_000,
                  p95_ms: 65_000,
                  answered_24h: 1,
                  speed_buckets: {
                    under_5s: 0,
                    from_5s_to_15s: 0,
                    from_15s_to_60s: 0,
                    over_60s: 1,
                  },
                },
              ],
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    renderWithClient(<AudiobookSettings />);

    expect(await screen.findAllByText("Connection performance")).toHaveLength(3);
    expect(screen.getByText("90% answered")).toBeInTheDocument();
    expect(screen.getByText("2.4 s")).toBeInTheDocument();
    expect(screen.getByLabelText("Gaming PC speed breakdown")).toHaveTextContent("<5s 8");
    expect(screen.getByText("TTS Host")).toBeInTheDocument();
    expect(screen.getByText("800 ms")).toBeInTheDocument();
    expect(screen.getByText("Speech Host")).toBeInTheDocument();
    expect(screen.getAllByText("1.1 min")).toHaveLength(3);
  });
});
