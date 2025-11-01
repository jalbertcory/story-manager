import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import EpubEditor from "./EpubEditor";

describe("EpubEditor", () => {
  it("renders EpubEditor and deletes a chapter", async () => {
    // Mock the fetch function
    global.fetch = vi.fn(() =>
      Promise.resolve({
        json: () => Promise.resolve([{ filename: "1", title: "Chapter 1" }]),
      })
    );

    render(<EpubEditor bookId={1} />);

    // Wait for the chapters to load
    await screen.findByText("Chapter 1");

    // Click the delete button
    fireEvent.click(screen.getByText("Delete"));

    // Check that the chapter is removed
    await waitFor(() => {
      expect(screen.queryByText("Chapter 1")).not.toBeInTheDocument();
    });
  });
});
