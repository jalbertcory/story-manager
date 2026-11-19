import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "../api/schema";
import { jsonResponse, mockFetch, renderWithClient } from "../test-utils";
import type { FixtureFetch } from "../test-utils";
import AudiobookOverview from "./AudiobookOverview";

type Overview = components["schemas"]["AudiobookOverviewResponse"];
type Source = components["schemas"]["AudiobookOverviewSource"];
type Book = components["schemas"]["AudiobookOverviewBook"];
type RebuildPreview = components["schemas"]["HumanAudiobookRebuildPreview"];

const source = (overrides: Partial<Source>): Source => ({
  kind: "human",
  edition_id: null,
  name: "Libation",
  state: "ready_whisper",
  state_label: "Human audio + Whisper",
  state_detail: null,
  next_action: null,
  next_action_label: null,
  processing_job_id: null,
  alignment_method: "transcribed",
  progress_current: 0,
  progress_total: 0,
  updated_at: null,
  ...overrides,
});

const overview: Overview = {
  transcription_configured: true,
  total_count: 4,
  attention_count: 3,
  counts: [
    { state: "import_failed", label: "Import failed", count: 1 },
    { state: "tts_failed", label: "AI narration failed", count: 1 },
    { state: "needs_review", label: "Needs match review", count: 1 },
    { state: "working", label: "In progress", count: 1 },
    { state: "ready_whisper", label: "Human audio + Whisper", count: 1 },
  ],
  books: [
    {
      book_id: 3,
      title: "Charlie",
      author: "Cee",
      has_epub: true,
      audio_kind: "human",
      state: "import_failed",
      needs_attention: true,
      sources: [
        source({
          edition_id: 31,
          state: "import_failed",
          state_label: "Import failed",
          state_detail: "Could not read the audio files.",
          next_action: "retry_import",
          next_action_label: "Retry import",
          alignment_method: "estimated",
        }),
      ],
    },
    {
      book_id: 5,
      title: "Echo",
      author: "Eve",
      has_epub: true,
      audio_kind: "both",
      state: "tts_failed",
      needs_attention: true,
      sources: [
        source({
          kind: "tts",
          name: "AI narration",
          state: "tts_failed",
          state_label: "Failed",
          state_detail: "Voice server offline",
          next_action: "open_generation",
          next_action_label: "Review and retry",
          alignment_method: null,
        }),
        source({
          edition_id: 51,
          state: "working",
          state_label: "Importing",
          state_detail: "Splitting chapters",
          progress_current: 2,
          progress_total: 5,
        }),
      ],
    },
    {
      book_id: 1,
      title: "Alpha",
      author: "Ann",
      has_epub: true,
      audio_kind: "human",
      state: "needs_review",
      needs_attention: true,
      sources: [
        source({
          edition_id: 11,
          state: "needs_review",
          state_label: "Needs review",
          next_action: "review_matches",
          next_action_label: "Review matches",
        }),
      ],
    },
    {
      book_id: 2,
      title: "Bravo",
      author: "Bea",
      has_epub: true,
      audio_kind: "human",
      state: "ready_whisper",
      needs_attention: false,
      sources: [source({ edition_id: 21 })],
    },
  ],
};

const rebuildPreview: RebuildPreview = {
  current_pipeline_version: 1,
  total_count: 5,
  rebuild_count: 2,
  realign_count: 1,
  up_to_date_count: 1,
  needs_review_count: 1,
  unavailable_count: 1,
};

// Answers the overview and the maintenance panel's rebuild preview; POSTs go
// to `post` when given.
function serve(data: Overview, post?: FixtureFetch) {
  return mockFetch((url, init) => {
    if (init?.method === "POST" && post) return post(url, init);
    if (url === "/api/audiobook/imports/rebuild-preview") {
      return Promise.resolve(jsonResponse(rebuildPreview));
    }
    return Promise.resolve(jsonResponse(data));
  });
}

const outdatedBook = (bookId: number, title: string, editionId: number) =>
  ({
    book_id: bookId,
    title,
    author: "Ann",
    has_epub: true,
    audio_kind: "human",
    state: "outdated",
    needs_attention: true,
    sources: [
      source({
        edition_id: editionId,
        state: "outdated",
        state_label: "Needs rebuild",
        next_action: "rebuild",
        next_action_label: "Rebuild",
      }),
    ],
  }) satisfies Book;

const outdated: Overview = {
  ...overview,
  total_count: 4,
  attention_count: 3,
  counts: [
    { state: "outdated", label: "Needs rebuild", count: 3 },
    { state: "ready_whisper", label: "Human audio + Whisper", count: 1 },
  ],
  books: [
    outdatedBook(1, "Alpha", 11),
    outdatedBook(2, "Bravo", 21),
    outdatedBook(3, "Charlie", 31),
    { ...overview.books[3]!, book_id: 4, title: "Delta" },
  ],
};

function titles() {
  return within(screen.getByRole("list", { name: "Audiobooks" }))
    .getAllByRole("link")
    .map((link) => link.textContent)
    .filter((text) => ["Alpha", "Bravo", "Charlie", "Echo"].includes(text));
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

describe("AudiobookOverview", () => {
  it("lists every audiobook with one state and action per source", async () => {
    serve(overview);
    renderWithClient(<AudiobookOverview />);

    expect(
      await screen.findByRole("link", { name: "Charlie" }),
    ).toHaveAttribute("href", "/books/3/audiobooks?tab=sources");
    expect(titles()).toEqual(["Charlie", "Echo", "Alpha", "Bravo"]);
    expect(screen.getByText("Could not read the audio files.")).toBeVisible();
    expect(screen.getByText("Eve · Human and AI narration")).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Review and retry" }),
    ).toHaveAttribute("href", "/books/5/audiobooks?tab=progress");
    expect(
      screen.getByRole("link", { name: "Review matches" }),
    ).toHaveAttribute("href", "/books/1/audiobooks?tab=sources");
    expect(
      screen.getByRole("progressbar", { name: "Libation progress" }),
    ).toHaveAttribute("max", "5");
    expect(screen.getByRole("button", { name: /^All 4$/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("filters by attention, by state and by search", async () => {
    serve(overview);
    renderWithClient(<AudiobookOverview />);
    await screen.findByRole("link", { name: "Bravo" });

    fireEvent.click(
      screen.getByRole("button", { name: /^Needs attention 3$/ }),
    );
    expect(titles()).toEqual(["Charlie", "Echo", "Alpha"]);

    // A book matches a state when any of its sources is in it.
    fireEvent.click(screen.getByRole("button", { name: /^In progress 1$/ }));
    expect(titles()).toEqual(["Echo"]);

    fireEvent.click(screen.getByRole("button", { name: /^All 4$/ }));
    fireEvent.change(screen.getByLabelText("Find audiobooks"), {
      target: { value: "bea" },
    });
    expect(titles()).toEqual(["Bravo"]);
  });

  it("opens with the state filter from the address", async () => {
    window.history.pushState({}, "", "/activity/audiobooks?state=needs_review");
    serve(overview);
    renderWithClient(<AudiobookOverview />);

    await screen.findByRole("link", { name: "Alpha" });
    expect(titles()).toEqual(["Alpha"]);
  });

  it("queues the edition's next action from the list", async () => {
    const posts: string[] = [];
    serve(overview, (url) => {
      posts.push(url);
      return Promise.resolve(jsonResponse({}));
    });
    renderWithClient(<AudiobookOverview />);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Retry import: Charlie, Libation",
      }),
    );

    expect(
      await screen.findByText("Retry import queued for Charlie.", {
        exact: false,
      }),
    ).toBeVisible();
    expect(posts).toEqual(["/api/imported-audiobooks/31/retry"]);
  });

  it("points to transcription settings when no provider is set up", async () => {
    serve({ ...overview, transcription_configured: false });
    renderWithClient(<AudiobookOverview />);

    expect(
      await screen.findByRole("link", { name: "Set up transcription" }),
    ).toHaveAttribute("href", "/settings/audio-ai");
  });

  it("retries the failed rematch job instead of reimporting its audio", async () => {
    const posts: string[] = [];
    const data: Overview = {
      ...overview,
      books: [
        {
          ...overview.books[0]!,
          state: "job_failed",
          sources: [
            source({
              edition_id: 31,
              processing_job_id: 72,
              state: "job_failed",
              state_label: "Processing failed",
              state_detail: "EPUB missing",
              next_action: "retry_processing",
              next_action_label: "Retry processing",
            }),
          ],
        },
      ],
    };
    serve(data, (url) => {
      posts.push(url);
      return Promise.resolve(jsonResponse({ id: 72, status: "queued" }));
    });
    renderWithClient(<AudiobookOverview />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Retry processing: Charlie, Libation",
      }),
    );
    await screen.findByText("Retry processing queued for Charlie.", {
      exact: false,
    });
    expect(posts).toEqual(["/api/processing/jobs/72/retry"]);
  });

  it("explains an empty library", async () => {
    serve({
      ...overview,
      total_count: 0,
      attention_count: 0,
      counts: [],
      books: [],
    });
    renderWithClient(<AudiobookOverview />);

    await waitFor(() =>
      expect(screen.getByText(/No audiobooks yet/)).toBeVisible(),
    );
  });

  it("queues one action for every audiobook shown in a state", async () => {
    const bodies: unknown[] = [];
    serve(outdated, (url, init) => {
      expect(url).toBe("/api/imported-audiobooks/bulk-action");
      bodies.push(JSON.parse(String(init?.body)));
      return Promise.resolve(
        jsonResponse({
          queued: [11, 21],
          skipped: [{ edition_id: 31, reason: "Queued" }],
        }),
      );
    });
    renderWithClient(<AudiobookOverview />);
    await screen.findByRole("link", { name: "Delta" });

    // Only a single state has one shared action to run.
    expect(
      screen.queryByRole("button", { name: /for all/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Needs rebuild 3$/ }));
    fireEvent.click(screen.getByRole("button", { name: "Rebuild for all 3" }));

    const dialog = screen.getByRole("dialog", {
      name: "Rebuild for 3 audiobooks?",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Queue all" }));

    expect(
      await screen.findByText(
        "Rebuild queued for 2 audiobooks. Skipped 1: Queued.",
        { exact: false },
      ),
    ).toBeVisible();
    expect(bodies).toEqual([{ action: "rebuild", edition_ids: [11, 21, 31] }]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("acts only on the audiobooks the search leaves showing", async () => {
    serve(outdated);
    renderWithClient(<AudiobookOverview />);
    await screen.findByRole("link", { name: "Delta" });
    fireEvent.click(screen.getByRole("button", { name: /^Needs rebuild 3$/ }));
    fireEvent.change(screen.getByLabelText("Find audiobooks"), {
      target: { value: "ha" },
    });
    expect(titles()).toEqual(["Alpha", "Charlie"]);
    expect(
      screen.getByRole("button", { name: "Rebuild for all 2" }),
    ).toBeVisible();

    // One audiobook is queued from its own row instead.
    fireEvent.change(screen.getByLabelText("Find audiobooks"), {
      target: { value: "alpha" },
    });
    expect(
      screen.queryByRole("button", { name: /for all/ }),
    ).not.toBeInTheDocument();
  });

  it("queues the audiobooks the confirmation named, even if the list changes", async () => {
    const bodies: unknown[] = [];
    serve(outdated, (_url, init) => {
      bodies.push(JSON.parse(String(init?.body)));
      return Promise.resolve(
        jsonResponse({ queued: [11, 21, 31], skipped: [] }),
      );
    });
    renderWithClient(<AudiobookOverview />);
    await screen.findByRole("link", { name: "Delta" });
    fireEvent.click(screen.getByRole("button", { name: /^Needs rebuild 3$/ }));
    fireEvent.click(screen.getByRole("button", { name: "Rebuild for all 3" }));

    fireEvent.change(screen.getByLabelText("Find audiobooks"), {
      target: { value: "ha" },
    });
    const dialog = screen.getByRole("dialog", {
      name: "Rebuild for 3 audiobooks?",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Queue all" }));

    await screen.findByText("Rebuild queued for 3 audiobooks.", {
      exact: false,
    });
    expect(bodies).toEqual([{ action: "rebuild", edition_ids: [11, 21, 31] }]);
  });

  it("resumes AI narration for every book shown paused", async () => {
    const pausedBook = (bookId: number, title: string) =>
      ({
        book_id: bookId,
        title,
        author: "Ann",
        has_epub: true,
        audio_kind: "tts",
        state: "tts_paused",
        needs_attention: true,
        sources: [
          source({
            kind: "tts",
            name: "AI narration",
            state: "tts_paused",
            state_label: "Paused",
            next_action: "open_generation",
            next_action_label: "Resume",
            alignment_method: null,
          }),
        ],
      }) satisfies Book;
    const posts: { url: string; body: unknown }[] = [];
    serve(
      {
        ...overview,
        total_count: 3,
        attention_count: 3,
        counts: [
          { state: "tts_paused", label: "AI narration paused", count: 3 },
        ],
        books: [
          pausedBook(1, "Alpha"),
          pausedBook(2, "Bravo"),
          pausedBook(3, "Charlie"),
        ],
      },
      (url, init) => {
        posts.push({ url, body: JSON.parse(String(init?.body)) });
        return Promise.resolve(
          jsonResponse({
            queued: [1, 2],
            skipped: [{ book_id: 3, reason: "Narration is already running" }],
          }),
        );
      },
    );
    renderWithClient(<AudiobookOverview />);
    await screen.findByRole("link", { name: "Charlie" });

    fireEvent.click(
      screen.getByRole("button", { name: /^AI narration paused 3$/ }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Resume narration for all 3" }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "Resume narration for 3 audiobooks?",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Queue all" }));

    expect(
      await screen.findByText(
        "Resume narration queued for 2 audiobooks. Skipped 1: Narration is already running.",
        { exact: false },
      ),
    ).toBeVisible();
    expect(posts).toEqual([
      {
        url: "/api/audiobook-narration/bulk-resume",
        body: { book_ids: [1, 2, 3] },
      },
    ]);
  });

  it("previews and queues versioned human audiobook rebuilds", async () => {
    const posts: string[] = [];
    serve(overview, (url) => {
      posts.push(url);
      return Promise.resolve(
        jsonResponse({
          queued_count: 2,
          skipped_count: 3,
          pipeline_version: 1,
        }),
      );
    });
    renderWithClient(<AudiobookOverview />);

    expect(
      await screen.findByRole("heading", { name: "Rebuild Human Audiobooks" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(
        "2 of 5 editions need updating · 1 need text timing updated · 1 currently unavailable · 1 need match review first",
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Import Libation backup" }),
    ).toHaveAttribute("href", "/import?type=libation");

    fireEvent.click(
      screen.getByRole("button", { name: "Rebuild outdated human audiobooks" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText(
        /Original audio and manual chapter corrections are preserved/,
      ),
    ).toBeVisible();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Queue rebuilds" }),
    );

    expect(
      await screen.findByText("2 human audiobook rebuilds queued; 3 skipped."),
    ).toBeVisible();
    expect(posts).toEqual(["/api/audiobook/imports/rebuild-all?force=false"]);
  });
});
