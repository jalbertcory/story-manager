import { screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import Utilities from "./Utilities";
import { renderWithClient } from "../test-utils";

describe("Utilities", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders all three utility sections", () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([]) }),
    );

    renderWithClient(<Utilities onBack={() => {}} />);

    expect(screen.getByRole("heading", { name: "Clean All Books" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Detect Series" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Storage Cleanup" })).toBeInTheDocument();
  });

  it("calls reprocess-all and shows Done on success", async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ reprocessed: 3 }) }),
    );

    renderWithClient(<Utilities onBack={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "Clean All Books" }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/books/reprocess-all",
        expect.objectContaining({ method: "POST" }),
      );
    });

    await waitFor(() => {
      expect(screen.getByText("Done.")).toBeInTheDocument();
    });
  });

  it("calls detect-series and shows results", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url.includes("detect-series")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({ updated: 2, series_detected: ["Dragon Saga", "Iron Path"] }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reprocessed: 0 }) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Detect Series in Library" }),
    );

    await waitFor(() => {
      expect(
        screen.getByText(/Updated 2 books: Dragon Saga, Iron Path/),
      ).toBeInTheDocument();
    });
  });

  it("shows 'No new series found' when detect-series finds nothing", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url.includes("detect-series")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ updated: 0, series_detected: [] }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reprocessed: 0 }) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Detect Series in Library" }),
    );

    await waitFor(() => {
      expect(screen.getByText("No new series found.")).toBeInTheDocument();
    });
  });

  it("shows orphaned files after scanning", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url.includes("storage/cleanup")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              dry_run: true,
              files: [{ path: "library/orphan.epub", size_bytes: 1024 }],
              total_bytes: 1024,
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reprocessed: 0 }) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Scan for Orphaned Files" }),
    );

    await waitFor(() => {
      expect(screen.getByText("library/orphan.epub")).toBeInTheDocument();
    });
  });
});
