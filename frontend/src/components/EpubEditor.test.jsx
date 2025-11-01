import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import EpubEditor from "./EpubEditor";

describe("EpubEditor", () => {
  const mockBook = {
    id: 1,
    title: "Test Book",
    removed_chapters: [],
    div_selectors: [],
  };

  const mockChapters = [
    { filename: "chap1.xhtml", title: "Chapter 1" },
    { filename: "chap2.xhtml", title: "Chapter 2" },
  ];

  it("fetches and displays chapters", async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockChapters),
      }),
    );

    render(<EpubEditor book={mockBook} onBack={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("Chapter 1")).toBeInTheDocument();
      expect(screen.getByText("Chapter 2")).toBeInTheDocument();
    });
  });

  it("allows toggling chapters", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockChapters),
    });

    render(<EpubEditor book={mockBook} onBack={() => {}} />);

    await waitFor(() => {
      fireEvent.click(screen.getByText("Chapter 1"));
    });

    // This is a simplified check; in a real app, you'd check state or a mock API call.
    // For this component, we can check the visual state.
    const chapter1Checkbox = screen.getAllByRole("checkbox")[0];
    expect(chapter1Checkbox.checked).toBe(true);
  });
});
