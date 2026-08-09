import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AttentionDashboard from "./AttentionDashboard";

const emptyCategory = { count: 0, items: [] };

function dashboard(overrides = {}) {
  return {
    total_count: 0,
    failed_jobs: emptyCategory,
    failed_refreshes: emptyCategory,
    stale_audiobooks: emptyCategory,
    metadata_proposals: emptyCategory,
    broken_files: emptyCategory,
    missing_covers: emptyCategory,
    ...overrides,
  };
}

describe("AttentionDashboard", () => {
  it("shows a clear healthy state", () => {
    render(<AttentionDashboard data={dashboard()} onRefresh={() => {}} />);

    expect(screen.getByText("Your library looks healthy.")).toBeInTheDocument();
    expect(screen.getAllByText("No attention needed")).toHaveLength(6);
  });

  it("shows actionable items and their destinations", () => {
    const data = dashboard({
      total_count: 3,
      failed_jobs: {
        count: 1,
        items: [
          {
            id: 8,
            job_type: "refresh_book",
            book_id: 2,
            book_title: "Failed Story",
            error: "Source unavailable",
          },
        ],
      },
      stale_audiobooks: {
        count: 1,
        items: [
          {
            book_id: 3,
            title: "Stale Audio",
            author: "Narrator",
            issue: "audiobook_stale",
            detail: "Generated audiobook needs reconciliation.",
          },
        ],
      },
      metadata_proposals: {
        count: 1,
        items: [
          {
            proposal_id: 9,
            book_id: 4,
            title: "Metadata Book",
            author: "Metadata Author",
            note: "Review genres",
          },
        ],
      },
    });

    render(<AttentionDashboard data={data} onRefresh={() => {}} />);

    expect(screen.getByText("Source unavailable")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review jobs" })).toHaveAttribute(
      "href",
      "/processing?status=error",
    );
    expect(screen.getByRole("link", { name: "Stale Audio" })).toHaveAttribute(
      "href",
      "/books/3/audiobooks?tab=sources",
    );
    expect(screen.getByRole("link", { name: "Review metadata" })).toHaveAttribute(
      "href",
      "/utilities?section=metadata",
    );
  });

  it("lets the user retry a failed dashboard request", () => {
    const refresh = vi.fn();
    render(
      <AttentionDashboard
        error={new Error("Dashboard unavailable")}
        onRefresh={refresh}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refresh).toHaveBeenCalledOnce();
  });
});
