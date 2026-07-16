import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AudiobookPipeline from "./AudiobookPipeline";
import { renderWithClient } from "../test-utils";

describe("AudiobookPipeline", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the actionable error and can run only the next stage", async () => {
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/books/11/audiobook/status") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              pipeline_status: "error",
              next_phase: "ingesting",
              pause_requested: false,
              stop_after_phase: null,
              last_error: "EPUB contains no narratable text.",
              sentence_counts: {},
            }),
        });
      }
      if (
        url === "/api/books/11/audiobook/characters" ||
        url === "/api/books/11/audiobook/chapters"
      ) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (
        url === "/api/books/11/audiobook/step" &&
        options?.method === "POST"
      ) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              status: "ingesting",
              queued: true,
              stop_after_phase: "ingesting",
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(<AudiobookPipeline book={{ id: 11 }} />);

    expect(
      await screen.findByText("EPUB contains no narratable text."),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Run Next Stage: Ingesting" }),
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/books/11/audiobook/step", {
        method: "POST",
      });
    });
  });
});
