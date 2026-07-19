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
    const ttsApiKeyInput = screen.getAllByLabelText("API Key")[1];
    fireEvent.change(ttsApiKeyInput, { target: { value: "openai-secret" } });
    fireEvent.change(providerSelect, {
      target: { value: "openai-compatible" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save & Test TTS" }));

    await waitFor(() => expect(updates).toHaveLength(1));
    expect(updates[0].tts_provider).toBe("openai-compatible");
    expect(updates[0]).not.toHaveProperty("tts_api_key");
  });
});
