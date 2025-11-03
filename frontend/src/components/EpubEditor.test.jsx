import { screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import EpubEditor from "./EpubEditor";
import { renderWithClient } from "../test-utils";

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

    renderWithClient(<EpubEditor book={mockBook} onBack={() => {}} />);

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

    renderWithClient(<EpubEditor book={mockBook} onBack={() => {}} />);

    let chapter1Checkbox;
    await waitFor(() => {
      // The checkbox is not directly associated with the text, so we get it by its role and name
      const chapter1Label = screen.getByText("Chapter 1");
      const chapter1Li = chapter1Label.closest("li");
      chapter1Checkbox = chapter1Li.querySelector("input[type='checkbox']");
      expect(chapter1Checkbox).toBeInTheDocument();
    });

    expect(chapter1Checkbox.checked).toBe(true);
    fireEvent.click(chapter1Checkbox);
    expect(chapter1Checkbox.checked).toBe(false);
  });
});
