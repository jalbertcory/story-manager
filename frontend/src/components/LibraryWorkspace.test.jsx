import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithClient } from "../test-utils";
import LibraryWorkspace from "./LibraryWorkspace";

const response = (value) =>
  Promise.resolve({ ok: true, json: async () => value });
const missing = {
  id: 948,
  title: "Artemis Fowl",
  author: "Eoin Colfer",
  series: "Artemis Fowl",
  source_type: "audiobook",
  has_epub: false,
};
afterEach(() => vi.unstubAllGlobals());

describe("Audio-only library", () => {
  it("keeps the missing EPUB filter when opening a series and returning from a book", async () => {
    const fetch = vi.fn((url) => {
      if (url.startsWith("/api/library/groups"))
        return response([
          {
            name: "Artemis Fowl",
            book_count: 1,
            audio_count: 1,
            author_count: 1,
            author: "Eoin Colfer",
            cover_ids: [],
          },
        ]);
      if (url.startsWith("/api/books/catalog")) return response([missing]);
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);
    const onEdit = vi.fn();
    const onNavigate = vi.fn();
    const renderPage = (search) => (
      <LibraryWorkspace
        search={search}
        onEdit={onEdit}
        onNavigate={onNavigate}
      />
    );
    const { rerender } = renderWithClient(
      renderPage("?group=series&source=audiobook"),
    );
    expect(screen.getByLabelText("Library source")).toHaveValue("audiobook");
    const seriesLink = await screen.findByRole("link", {
      name: /Artemis Fowl/,
    });
    expect(seriesLink).toHaveAttribute(
      "href",
      "/?group=series&series=Artemis+Fowl&source=audiobook",
    );
    expect(
      fetch.mock.calls.some(
        ([url]) => url.includes("groups?") && url.includes("source=audiobook"),
      ),
    ).toBe(true);
    rerender(renderPage("?group=series&series=Artemis+Fowl&source=audiobook"));
    await screen.findByText("Audio only");
    expect(
      fetch.mock.calls.some(
        ([url]) =>
          url.includes("catalog?") &&
          url.includes("source=audiobook") &&
          url.includes("series=Artemis%20Fowl"),
      ),
    ).toBe(true);
    expect(screen.queryByText("Organize this series")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("link", { name: /Artemis Fowl Eoin Colfer/ }),
    );
    expect(onEdit).toHaveBeenCalledWith(
      expect.objectContaining({ id: 948 }),
      "/?group=series&series=Artemis+Fowl&source=audiobook",
    );
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute(
      "href",
      "/?group=series&source=audiobook",
    );
  });

  it("offers audio-only filtering without grouping", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url) =>
        response(url.startsWith("/api/books/catalog") ? [missing] : []),
      ),
    );
    const onNavigate = vi.fn();
    renderWithClient(
      <LibraryWorkspace
        search="?group=none"
        onEdit={vi.fn()}
        onNavigate={onNavigate}
      />,
    );
    fireEvent.change(screen.getByLabelText("Library source"), {
      target: { value: "audiobook" },
    });
    expect(onNavigate).toHaveBeenCalledWith("/?group=none&source=audiobook");
    await waitFor(() =>
      expect(screen.getByText("Audio only")).toBeInTheDocument(),
    );
  });
});
